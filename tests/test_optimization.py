import numpy as np
import tensorflow as tf
import unittest

from timemachine import bonded_force
from timemachine.constants import BOLTZ
from timemachine import integrator
from timemachine import observable
from timemachine.reservoir_sampler import ReservoirSampler

class TestOptimization(unittest.TestCase):

    def tearDown(self):
        tf.reset_default_graph()

    def test_optimize_ensemble(self):

        # 1. Generate a water ensemble by doing 5000 steps of MD starting from an idealized geometry.
        # 2. Reservoir sample along the trajectory.
        # 3. Generate a loss function used sum of square distances.
        # 4. Compute parameter derivatives.

        x_opt = np.array([
            [-0.0070, -0.0100, 0.0000],
            [-0.1604,  0.4921, 0.0000],
            [ 0.5175,  0.0128, 0.0000],
        ], dtype=np.float64) # idealized geometry

        
        masses = np.array([8.0, 1.0, 1.0], dtype=np.float64)
        num_atoms = len(masses)

        ideal_bond = 0.52
        ideal_angle = 2.1 # Guessestimate ending (true x_opt: 1.81)

        bond_params = [
            tf.get_variable("OH_kb", shape=tuple(), dtype=tf.float64, initializer=tf.constant_initializer(100.0)),
            tf.get_variable("OH_b0", shape=tuple(), dtype=tf.float64, initializer=tf.constant_initializer(ideal_bond)),
        ]

        hb = bonded_force.HarmonicBondForce(
            params=bond_params,
            bond_idxs=np.array([[0,1],[0,2]], dtype=np.int32),
            param_idxs=np.array([[0,1],[0,1]], dtype=np.int32)
        )

        angle_params = [
            tf.get_variable("HOH_ka", shape=tuple(), dtype=tf.float64, initializer=tf.constant_initializer(75.0)),
            tf.get_variable("HOH_a0", shape=tuple(), dtype=tf.float64, initializer=tf.constant_initializer(ideal_angle)),
        ]

        ha = bonded_force.HarmonicAngleForce(
            params=angle_params,
            angle_idxs=np.array([[1,0,2]], dtype=np.int32),
            param_idxs=np.array([[0,1]], dtype=np.int32)
        )

        friction = 1.0
        dt = 0.005
        temp = 300.0

        x_ph = tf.placeholder(name="input_geom", dtype=tf.float64, shape=(num_atoms, 3))
        intg = integrator.LangevinIntegrator(
            masses, x_ph, [hb, ha], dt, friction, temp, disable_noise=False, buffer_size=500)

        num_steps = 5000
        reservoir_size = 500

        ref_dx_op, ref_dxdp_op = intg.step_op()

        sess = tf.Session()
        sess.run(tf.initializers.global_variables())

        def reference_generator():
            x = x_opt
            for step in range(num_steps):
                if step % 100 == 0:
                    print(step)
                dx_val, dxdp_val = sess.run([ref_dx_op, ref_dxdp_op], feed_dict={x_ph: x})
                x += dx_val
                # this copy is important here, otherwise we're just adding the same reference
                # since += modifies the object in_place
                yield np.copy(x), dxdp_val, step # wip: decouple


        def generate_reference_ensemble():
            intg.reset(sess)
            rs = ReservoirSampler(reference_generator(), reservoir_size)
            rs.sample_all()
            
            ensemble = []
            ensemble_grads = []
            for x, dxdp, t in rs.R:
                ensemble.append(x)
                ensemble_grads.append(dxdp)
            stacked_ensemble = np.stack(ensemble, axis=0)


            ensemble_ph = tf.placeholder(shape=(reservoir_size, num_atoms, 3), dtype=np.float64)

            ref_d2ij_op = observable.sorted_squared_distances(ensemble_ph)
            return ref_d2ij_op, stacked_ensemble, ensemble_ph

        a1, inp1, ensemble_ph1 = generate_reference_ensemble()
        a2, inp2, ensemble_ph2 = generate_reference_ensemble()

        # compute MSE of two _identical_ simulations except for the RNG
        loss = tf.reduce_sum(tf.pow(a1-a2, 2))/reservoir_size # 0.003

        

        print("MSE", sess.run(loss, feed_dict={ensemble_ph1: inp1, ensemble_ph2: inp2}))
        


        sess.run([tf.assign(bond_params[1], 1.1), tf.assign(angle_params[1], 1.8)])

        friction = 10.0
        dt = 0.05
        temp = 250.0

        x_ph = tf.placeholder(name="input_geom", dtype=tf.float64, shape=(num_atoms, 3))

        with tf.variable_scope("bad"):
            bad_intg = integrator.LangevinIntegrator(
                masses, x_ph, [hb, ha], dt, friction, temp, disable_noise=False, buffer_size=500)

        bad_dx_op, bad_dxdp_op = bad_intg.step_op()

        def sub_optimal_generator():
            x = x_opt
            for step in range(num_steps):
                if step % 100 == 0:
                    print(step)
                dx_val, dxdp_val = sess.run([bad_dx_op, bad_dxdp_op], feed_dict={x_ph: x})
                x += dx_val
                # this copy is important here, otherwise we're just adding the same reference
                # since += modifies the object in_place
                yield np.copy(x), dxdp_val, step # wip: decouple


        def generate_sub_optimal_ensemble():
            bad_intg.reset(sess)
            rs = ReservoirSampler(sub_optimal_generator(), reservoir_size)
            rs.sample_all()
            
            ensemble = []
            ensemble_grads = []
            for x, dxdp, t in rs.R:
                ensemble.append(x)
                ensemble_grads.append(dxdp)
            stacked_ensemble = np.stack(ensemble, axis=0)
            ensemble_ph = tf.placeholder(shape=(reservoir_size, num_atoms, 3), dtype=np.float64)

            ref_d2ij_op = observable.sorted_squared_distances(ensemble_ph)
            return ref_d2ij_op, stacked_ensemble, ensemble_ph

        b1, bnp1, bensemble_ph1 = generate_sub_optimal_ensemble()
        loss = tf.reduce_sum(tf.pow(a1-b1, 2))/reservoir_size # 0.003
        print("MSE", sess.run(loss, feed_dict={ensemble_ph1: inp1, bensemble_ph1: bnp1})) #MSE 12.953122852970827

        # rs2.sample_all()

        # fit to self to measure precision




    # def test_optimize_single_structure(self):
    #     """
    #     Testing optimization of a single structure.
    #     """
    #     masses = np.array([8.0, 1.0, 1.0])
    #     x0 = np.array([
    #         [-0.0070, -0.0100, 0.0000],
    #         [-1.1426,  0.5814, 0.0000],
    #         [ 0.4728, -0.2997, 0.0000],
    #     ], dtype=np.float64) # starting geometry

    #     x_opt = np.array([
    #         [-0.0070, -0.0100, 0.0000],
    #         [-0.1604,  0.4921, 0.0000],
    #         [ 0.5175,  0.0128, 0.0000],
    #     ], dtype=np.float64) # idealized geometry

    #     bonds = x_opt - x_opt[0, :]
    #     bond_lengths = np.linalg.norm(bonds[1:, :], axis=1)

    #     num_atoms = len(masses)

    #     starting_bond = 0.8 # Guessestimate starting (true x_opt: 0.52)
    #     starting_angle = 2.1 # Guessestimate ending (true x_opt: 1.81)

    #     bond_params = [
    #         tf.get_variable("OH_kb", shape=tuple(), dtype=tf.float64, initializer=tf.constant_initializer(100.0)),
    #         tf.get_variable("OH_b0", shape=tuple(), dtype=tf.float64, initializer=tf.constant_initializer(starting_bond)),
    #     ]

    #     hb = bonded_force.HarmonicBondForce(
    #         params=bond_params,
    #         bond_idxs=np.array([[0,1],[0,2]], dtype=np.int32),
    #         param_idxs=np.array([[0,1],[0,1]], dtype=np.int32)
    #     )

    #     angle_params = [
    #         tf.get_variable("HOH_ka", shape=tuple(), dtype=tf.float64, initializer=tf.constant_initializer(75.0)),
    #         tf.get_variable("HOH_a0", shape=tuple(), dtype=tf.float64, initializer=tf.constant_initializer(starting_angle)),
    #     ]

    #     ha = bonded_force.HarmonicAngleForce(
    #         params=angle_params,
    #         angle_idxs=np.array([[1,0,2]], dtype=np.int32),
    #         param_idxs=np.array([[0,1]], dtype=np.int32)
    #     )

    #     friction = 10.0
    #     dt = 0.005
    #     temp = 300.0

    #     x_ph = tf.placeholder(name="input_geom", dtype=tf.float64, shape=(num_atoms, 3))
    #     intg = integrator.LangevinIntegrator(
    #         masses, x_ph, [hb, ha], dt, friction, temp, disable_noise=True, buffer_size=400)

    #     dx_op, dxdp_op = intg.step_op()

    #     num_steps = 500

    #     param_optimizer = tf.train.AdamOptimizer(0.02)

    #     def loss(pred_x):

    #         # Compute pairwise distances
    #         def dij(x):
    #             v01 = x[0]-x[1]
    #             v02 = x[0]-x[2]
    #             v12 = x[1]-x[2]
    #             return tf.stack([tf.norm(v01), tf.norm(v02), tf.norm(v12)])

    #         return tf.norm(dij(x_opt) - dij(pred_x))

    #     # geometry we arrive at at time t=inf
    #     x_final_ph = tf.placeholder(dtype=tf.float64, shape=(num_atoms, 3))
    #     dLdx = tf.gradients(loss(x_final_ph), x_final_ph)

    #     grads_and_vars = intg.grads_and_vars(dLdx)
    #     train_op = param_optimizer.apply_gradients(grads_and_vars)

    #     sess = tf.Session()
    #     sess.run(tf.initializers.global_variables())

    #     num_epochs = 75

    #     for e in range(num_epochs):
    #         print("starting epoch", e, "current params", sess.run(bond_params+angle_params))
    #         x = x0  
    #         intg.reset(sess) # clear integration buffers
    #         for step in range(num_steps):
    #             dx_val, dxdp_val = sess.run([dx_op, dxdp_op], feed_dict={x_ph: x})
    #             x += dx_val

    #         sess.run(train_op, feed_dict={x_final_ph: x})

    #     params = sess.run(bond_params+angle_params)
    #     np.testing.assert_almost_equal(params[1], 0.52, decimal=2)
    #     np.testing.assert_almost_equal(params[3], 1.81, decimal=1)
           
if __name__ == "__main__":
    unittest.main()