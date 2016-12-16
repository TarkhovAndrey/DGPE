import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import minimize

class DynamicsGenerator(object):
	def __init__(self, **kwargs):
		#Hamiltonian parameters
		self.J = kwargs.get('J', 1.0)
		self.beta = kwargs.get('beta', 0.01)
		self.W = kwargs.get('W', 0.)

		self.N_tuple = kwargs.get('N_wells', 10)
		self.dimensionality = kwargs.get('dimensionality', 1)
		self.Nx = 1
		self.Ny = 1
		self.Nz = 1
		if type(self.N_tuple) == type(5):
			self.Nx = self.N_tuple
			self.N_tuple = (self.Nx, self.Ny, self.Nz)
		elif len(self.N_tuple) == 2:
			self.Nx = self.N_tuple[0]
			self.Ny = self.N_tuple[1]
			self.N_tuple = (self.Nx, self.Ny, self.Nz)
		elif len(self.N_tuple) == 3:
			self.Nx = self.N_tuple[0]
			self.Ny = self.N_tuple[1]
			self.Nz = self.N_tuple[2]
		if self.Ny > 1:
			self.dimensionality = 2
		if self.Nz > 1:
			self.dimensionality = 3
		self.N_wells = self.Nx * self.Ny * self.Nz
		self.wells_indices = [(i,j,k) for i in xrange(self.Nx) for j in xrange(self.Ny) for k in xrange(self.Nz)]

		#Seeds
		self.disorder_seed = kwargs.get('disorder_seed', 78)
		self.traj_seed = kwargs.get('traj_seed', 78)
		self.pert_seed = kwargs.get('pert_seed', 123)

		self.generate_disorder()

		self.N_part = kwargs.get('N_part_per_well', 100000)
		self.N_part *= self.N_wells
		self.step = kwargs.get('step', 5.7e-05)
		self.tau_char = kwargs.get('tau_char', 1.0 / np.sqrt(3. * self.beta * self.J * self.N_part/self.N_wells))
		self.time = kwargs.get('time', 1.4 * 50)
		self.time *= self.tau_char
		self.n_steps = kwargs.get('n_steps', int(self.time / self.step))

		self.FloatPrecision = kwargs.get('FloatPrecision', np.float128)

		self.E_calibr = kwargs.get('E_calibr', 0)
		if self.dimensionality == 1:
			self.threshold_XY_to_polar = kwargs.get('threshold_XY_to_polar', 1.)
		else:
			self.threshold_XY_to_polar = kwargs.get('threshold_XY_to_polar', 2.)

		self.energy = np.zeros(self.n_steps, dtype=self.FloatPrecision)
		self.participation_rate = np.zeros(self.n_steps, dtype=self.FloatPrecision)
		self.effective_nonlinearity = np.zeros(self.n_steps, dtype=self.FloatPrecision)
		self.number_of_particles = np.zeros(self.n_steps, dtype=self.FloatPrecision)
		self.histograms = {}
		self.rho_histograms = {}

		self.T = np.linspace(0, self.time, self.n_steps)
		self.RHO = np.zeros(self.N_tuple + (self.n_steps,), dtype=self.FloatPrecision)
		self.THETA = np.zeros(self.N_tuple + (self.n_steps,), dtype=self.FloatPrecision)
		self.X = np.zeros(self.N_tuple + (self.n_steps,), dtype=self.FloatPrecision)
		self.Y = np.zeros(self.N_tuple + (self.n_steps,), dtype=self.FloatPrecision)
		self.consistency_checksum = 0
		self.error_code = ""
		self.configure(kwargs)

	def configure(self, kwargs):
		self.PERT_EPS = 1e-8
		self.FTOL = kwargs.get('FTOL', 1e-14)
		self.E_eps = kwargs.get('E_eps', 1e-2)
		self.singular_eps = 1e-8

	def generate_disorder(self):
		np.random.seed(self.disorder_seed)
		self.e_disorder = -self.W  + 2. * self.W * np.random.rand(self.N_tuple[0], self.N_tuple[1], self.N_tuple[2])
		np.random.seed()

	def phase_unwrap(self, theta):
		return theta

	def set_init_XY(self, x, y):
		self.X[:,:,:,0] = x.reshape(self.N_tuple)
		self.Y[:,:,:,0] = y.reshape(self.N_tuple)
		self.RHO[:,:,:,0], self.THETA[:,:,:,0] = self.from_XY_to_polar(self.X[:,:,:,0], self.Y[:,:,:,0])

	def from_polar_to_XY(self, rho, theta):
		rho = np.abs(rho)
		theta = self.phase_unwrap(theta)
		return rho * np.cos(theta), rho * np.sin(theta)

	def from_XY_to_polar(self, x, y):
		rho = np.sqrt((x ** 2) + (y ** 2))
		theta = np.arctan2(y, x)
		theta = self.phase_unwrap(theta)
		return rho, theta

	def constant_perturbation_XY(self, x0, y0):
		np.random.seed(self.pert_seed)
		eps = 1e-1
		x1 = x0 + eps * np.random.randn(self.N_tuple[0],self.N_tuple[1], self.N_tuple[2])
		y1 = y0 + eps * np.random.randn(self.N_tuple[0],self.N_tuple[1], self.N_tuple[2])
		dist = self.calc_traj_shift_XY(x0, y0, x1, y1)
		x1 = x0 + (x1 - x0) * self.PERT_EPS /dist
		y1 = y0 + (y1 - y0) * self.PERT_EPS /dist
		return x1, y1

	def generate_init(self, kind, traj_seed, energy_per_site):
		np.random.seed(traj_seed)
		rho = np.array(np.sqrt(1.0 * self.N_part/self.N_wells) * np.ones(self.N_tuple))
		theta = np.zeros(self.N_tuple, dtype=self.FloatPrecision)
		if kind == 'random':
			print "random"
			theta += 2. * np.pi * np.random.rand(self.N_tuple[0], self.N_tuple[1], self.N_tuple[2])
		elif kind =='AF':
			for i in self.N_tuple:
				if i % 2 == 1:
					theta[i] = np.pi/2
				else:
					theta[i] = 0
			theta += 0.1 * np.pi * np.random.randn(self.N_tuple[0], self.N_tuple[1], self.N_tuple[2])
		theta = self.phase_unwrap(theta)
		self.RHO[:,:,:,0] = rho.reshape(self.N_tuple)
		self.THETA[:,:,:,0] = theta.reshape(self.N_tuple)
		self.X[:,:,:,0], self.Y[:,:,:,0] = self.from_polar_to_XY(self.RHO[:,:,:,0], self.THETA[:,:,:,0])
		self.E_calibr = 1.0 * energy_per_site * self.N_wells
		#self.calc_energy_XY(self.X[0,:], self.Y[0,:], 0)

	def rk4_step_exp(self, y0, *args):
		# y0[:self.N_wells] = np.abs(y0[:self.N_wells])
		# y0[self.N_wells:] = self.phase_unwrap(y0[self.N_wells:])

		h = self.step
		k1 = h * self.Hamiltonian(y0)

		y2 = y0 + (k1/2.)
		# y2[:self.N_wells] = np.abs(y2[:self.N_wells])
		# y2[self.N_wells:] = self.phase_unwrap(y2[self.N_wells:])
		k2 = h * self.Hamiltonian(y2)

		y3 = y0 + (k2/2.)
		# y3[:self.N_wells] = np.abs(y3[:self.N_wells])
		# y3[self.N_wells:] = self.phase_unwrap(y3[self.N_wells:])
		k3 = h * self.Hamiltonian(y3)

		y4 = y0 + k3
		# y4[:self.N_wells] = np.abs(y4[:self.N_wells])
		# y4[self.N_wells:] = self.phase_unwrap(y4[self.N_wells:])
		k4 = h * self.Hamiltonian(y4)

		yi = y0 + (k1 + 2.*k2 + 2.*k3 + k4)/6.

		# yi[:self.N_wells] = np.abs(yi[:self.N_wells])
		# yi[self.N_wells:] = self.phase_unwrap(yi[self.N_wells:])

		return yi

	def rk4_step_exp_XY(self, y0, *args):

		h = self.step
		k1 = h * self.HamiltonianXY(y0)

		y2 = y0 + (k1/2.)
		k2 = h * self.HamiltonianXY(y2)

		y3 = y0 + (k2/2.)
		k3 = h * self.HamiltonianXY(y3)

		y4 = y0 + k3
		k4 = h * self.HamiltonianXY(y4)

		yi = y0 + (k1 + 2.*k2 + 2.*k3 + k4)/6.
		return yi

	def run_dynamics(self):
		for i in xrange(1, self.n_steps):
			if (np.any(self.RHO[:,:,:,i-1] ** 2 < self.threshold_XY_to_polar)):
				psi = self.rk4_step_exp_XY(np.hstack((self.X[:,:,:,i-1].flatten(), self.Y[:,:,:,i-1].flatten())))
				self.X[:,:,:,i] = psi[:self.N_wells].reshape(self.N_tuple)
				self.Y[:,:,:,i] = psi[self.N_wells:].reshape(self.N_tuple)
				self.RHO[:,:,:,i], self.THETA[:,:,:,i] = self.from_XY_to_polar(self.X[:,:,:,i], self.Y[:,:,:,i])
				self.X[:,:,:,i], self.Y[:,:,:,i] = self.from_polar_to_XY(self.RHO[:,:,:,i], self.THETA[:,:,:,i])
			else:
				psi = self.rk4_step_exp(np.hstack((self.RHO[:,:,:,i-1].flatten(), self.THETA[:,:,:,i-1].flatten())))
				self.RHO[:,:,:,i] = psi[:self.N_wells].reshape(self.N_tuple)
				self.THETA[:,:,:,i] = psi[self.N_wells:].reshape(self.N_tuple)
				self.X[:,:,:,i], self.Y[:,:,:,i] = self.from_polar_to_XY(self.RHO[:,:,:,i], self.THETA[:,:,:,i])
		self.energy, self.number_of_particles, self.angular_momentum = self.calc_constants_of_motion(self.RHO, self.THETA, self.X, self.Y)

	def reverse_hamiltonian(self, error_J, error_beta, error_disorder):
		self.J = -1. * self.J * (1.0 + error_J * np.random.randn())
		self.beta = -1. * self.beta * (1.0 + error_beta * np.random.randn())
		self.e_disorder = -1. * self.e_disorder * (1.0 + error_disorder * np.random.randn())

	def Hamiltonian(self, psi):
		rho0 = psi[:self.N_wells].reshape(self.N_tuple)
		theta0 = psi[self.N_wells:].reshape(self.N_tuple)
		rho = np.zeros(self.N_tuple, dtype=self.FloatPrecision)
		theta = np.zeros(self.N_tuple, dtype=self.FloatPrecision)
		for i in self.wells_indices:
			theta[i] += - self.beta * (rho0[i]**2) - self.e_disorder[i]
			for j in self.nearest_neighbours(i):
				rho[i] -= self.J * (rho0[j] * np.sin(theta0[j]-theta0[i]))
				dThetaJ = self.J  * (rho0[j] * np.cos(theta0[j]-theta0[i]))
				theta[i] += 1.0 / rho0[i] * dThetaJ
		return np.hstack((rho.flatten(),theta.flatten()))

	def effective_frequency(self, X0, Y0):
		return self.E_calibr

	def NN(self, i):
		j = []
		for idx in xrange(len(i)):
			if i[idx] < 0:
				j.append(self.N_tuple[idx] - 1)
			elif i[idx] == self.N_tuple[idx]:
				j.append(0)
			else:
				j.append(i[idx])
		return tuple(j)

	def nearest_neighbours(self, i):
		if self.dimensionality == 1:
			return [self.NN( (i[0] + 1, i[1], i[2]) ), self.NN( (i[0] - 1, i[1], i[2]) )]
		elif self.dimensionality == 2:
			return [self.NN( (i[0] + 1, i[1], i[2]) ), self.NN( (i[0] - 1, i[1], i[2]) ),
			        self.NN( (i[0], i[1] + 1, i[2]) ), self.NN( (i[0], i[1] - 1, i[2]) )]
		elif self.dimensionality == 3:
			return [self.NN( (i[0] + 1, i[1], i[2]) ), self.NN( (i[0] - 1, i[1], i[2]) ),
			        self.NN( (i[0], i[1] + 1, i[2]) ), self.NN( (i[0], i[1] - 1, i[2]) ),
			        self.NN( (i[0], i[1], i[2]-1) ), self.NN( (i[0], i[1], i[2]+1) )]
		else:
			return 0

	def HamiltonianXY(self, psi):
		X0 = psi[:self.N_wells].reshape(self.N_tuple)
		Y0 = psi[self.N_wells:].reshape(self.N_tuple)

		dX = np.zeros(self.N_tuple, dtype=self.FloatPrecision)
		dY = np.zeros(self.N_tuple, dtype=self.FloatPrecision)

		for i in self.wells_indices:
			dX[i] += self.e_disorder[i] * Y0[i]
			dY[i] += - self.e_disorder[i] * X0[i]
			for j in self.nearest_neighbours(i):
				dX[i] += -self.J * Y0[j]
				dY[i] += self.J * X0[j]
		dX += self.beta * ((Y0 ** 2) + (X0 ** 2)) * Y0
		dY += - self.beta * ((Y0 ** 2) + (X0 ** 2)) * X0

		return np.hstack((dX.flatten(),dY.flatten()))

	def Jacobian(self, psi, t):
		# X - RHO, Y - THETA
		X0 = np.array(psi[:self.N_wells], dtype=self.FloatPrecision)
		Y0 = np.array(psi[self.N_wells:], dtype=self.FloatPrecision)

		dFdXY = np.zeros((2 * self.N_wells, 2 * self.N_wells), dtype=self.FloatPrecision)
		for i in xrange(X0.shape[0]):
			# dXi / dXj
			dFdXY[i,self.NN(i-1)] += - self.J * np.cos(Y0[self.NN(i-1)] - Y0[i])
			dFdXY[i,self.NN(i+1)] += - self.J * np.cos(Y0[self.NN(i+1)] - Y0[i])
			# dXi / dYj
			dFdXY[i,i+self.N_wells] += - self.J * (X0[self.NN(i-1)] * (np.sin(Y0[self.NN(i-1)] - Y0[i])) +
			                             X0[self.NN(i+1)] * (np.sin(Y0[self.NN(i+1)] - Y0[i])))

			dFdXY[i,self.NN(i+1)+self.N_wells] += self.J * (X0[self.NN(i+1)] * (np.sin(Y0[self.NN(i+1)] - Y0[i])))
			dFdXY[i,self.NN(i-1)+self.N_wells] += self.J * (X0[self.NN(i-1)] * (np.sin(Y0[self.NN(i-1)] - Y0[i])))

			# dYi / dYj
			dFdXY[i+self.N_wells,i+self.N_wells] += self.J * (X0[self.NN(i-1)]/X0[i] * (np.sin(Y0[self.NN(i-1)] - Y0[i])) +
			                                   X0[self.NN(i+1)] / X0[i] * (np.sin(Y0[self.NN(i+1)] - Y0[i])))
			dFdXY[i+self.N_wells,self.NN(i+1)+self.N_wells] += - self.J * (X0[self.NN(i+1)]/X0[i] * (np.sin(Y0[self.NN(i+1)] - Y0[i])))
			dFdXY[i+self.N_wells,self.NN(i-1)+self.N_wells] += - self.J * (X0[self.NN(i-1)]/X0[i] * (np.sin(Y0[self.NN(i-1)] - Y0[i])))
			# dYi / dXj
			dFdXY[i+self.N_wells,i] += - 2.0 * self.beta * X0[i] - self.J * (
				X0[self.NN(i-1)]/ (X0[i] ** 2) * (np.cos(Y0[self.NN(i-1)] - Y0[i])) +
				X0[self.NN(i+1)] / (X0[i] ** 2) * (np.cos(Y0[self.NN(i+1)] - Y0[i])))
			dFdXY[i+self.N_wells,self.NN(i+1)] += self.J * (1./X0[i] * (np.cos(Y0[self.NN(i+1)] - Y0[i])))
			dFdXY[i+self.N_wells,self.NN(i-1)] += self.J * (1./X0[i] * (np.cos(Y0[self.NN(i-1)] - Y0[i])))

		return dFdXY

	def calc_constants_of_motion(self, RHO, THETA, X, Y):
		number_of_particles = np.sum(RHO ** 2, axis=(0,1,2))
		energy = np.zeros(self.n_steps, dtype=self.FloatPrecision)
		angular_momentum = np.zeros(self.n_steps, dtype=self.FloatPrecision)
		for j in self.wells_indices:
			energy += (self.beta/2. * np.abs(RHO[j]**4) +
			           self.e_disorder[j] * np.abs(RHO[j]**2))
			for k in self.nearest_neighbours(j):
				energy += (- self.J * (RHO[k] * RHO[j] * np.cos(THETA[k] - THETA[j])))
			# angular_momentum += - 2 * self.J * (X[:,j] * (0*Y[:,self.NN(j-1)] + Y[:,self.NN(j+1)]) - Y[:,j] * (0*X[:,self.NN(j-1)] + X[:,self.NN(j+1)]))
			# angular_momentum += - 2 * self.J * (X[:,j] * (0*Y[:,self.NN(j-1)] + Y[:,self.NN(j+1)]) - 0*Y[:,j] * (0*X[:,self.NN(j-1)] + X[:,self.NN(j+1)]))
			# angular_momentum += - 2 * self.J * (X[:,j] * (1./3*X[:,j] ** 2 + Y[:,j] ** 2))
			angular_momentum += - 2 * self.J * (X[j] * Y[k] - Y[j] * X[k])

		return energy, number_of_particles, angular_momentum

	def set_constants_of_motion(self):
		self.energy, self.number_of_particles, self.angular_momentum = self.calc_constants_of_motion(self.RHO, self.THETA, self.X, self.Y)
		for i in self.wells_indices:
			self.histograms[i] = np.histogram2d(np.float64(self.X[i]), np.float64(self.Y[i]), bins=100)
			self.rho_histograms[i] = np.histogram(np.float64(self.RHO[i] ** 2), bins=100)

		self.participation_rate = np.sum(self.RHO ** 4, axis=(0,1,2)) / (np.sum(self.RHO ** 2, axis=(0,1,2)) ** 2)
		self.effective_nonlinearity = self.beta * (self.participation_rate) / self.N_wells

	def calc_traj_shift_XY(self, x0, y0, x1, y1):
		return np.sqrt(np.sum( ((x0 - x1) ** 2 + (y0 - y1) ** 2).flatten() ))

	def calc_energy_XY(self, x, y, E):
		E_new = -E
		for j in self.wells_indices:
			E_new += (self.beta/2. * ((x[j]**2 + y[j]**2)**2) +
			         self.e_disorder[j] * (x[j]**2 + y[j]**2))
			for k in self.nearest_neighbours(j):
				E_new += (-self.J * (x[j] * x[k] + y[j] * y[k]))
		return E_new

	def calc_angular_momentum_XY(self, x, y):
		L = 0
		for j in self.wells_indices:
			for k in self.nearest_neighbours(j):
				L += - 2 * self.J * x[j] * y[k]
		return L

	def calc_full_energy_XY(self, x, y):
		E_kin = 0
		E_pot = 0
		E_noise = 0
		for j in self.wells_indices:
			for k in self.nearest_neighbours(j):
				E_kin += (-self.J * (x[j] * x[k] + y[j] * y[k]))
			E_pot += self.beta/2. * ((x[j]**2 + y[j]**2)**2)
			E_noise += self.e_disorder[j] * (x[j]**2 + y[j]**2)

		return E_kin, E_pot, E_noise

	def calc_number_of_particles_XY(self, x, y):
		return (np.sum((x ** 2) + (y ** 2)) - self.N_part)

	def make_exception(self, code):
		self.error_code += code
		self.consistency_checksum = 1

	def E_const_perturbation_XY(self, x0, y0, delta):
		bnds = np.hstack((x0.flatten(), y0.flatten()))
		x_err = 1./self.dimensionality * delta #0.01 * x0
		y_err = 1./self.dimensionality * delta #0.01 * y0
		np.random.seed()
		x_next = x0 + x_err * np.random.randn(self.N_tuple[0], self.N_tuple[1], self.N_tuple[2])
		y_next = y0 + y_err * np.random.randn(self.N_tuple[0], self.N_tuple[1], self.N_tuple[2])
		zero_app = np.hstack((x_next.flatten(), y_next.flatten()))
		fun = lambda x: (((self.calc_energy_XY(x[:self.N_wells].reshape(self.N_tuple),
		                                       x[self.N_wells:].reshape(self.N_tuple),
		                                       self.E_calibr))/self.E_calibr) ** 2 +
		                 (self.calc_number_of_particles_XY(x[:self.N_wells].reshape(self.N_tuple),
		                                                   x[self.N_wells:].reshape(self.N_tuple)
		                                                   )/self.N_part) ** 2)

		opt = minimize(fun, zero_app,
		               bounds=[(xi - 1.0 * delta, xi + 1.0 * delta) for xi in bnds],
		               options={'ftol':self.FTOL})

		col = 0
		while (col < 10) and ((opt.success == False) or
			                      (np.abs(self.calc_energy_XY(opt.x[:self.N_wells].reshape(self.N_tuple),
			                                                  opt.x[self.N_wells:].reshape(self.N_tuple),
			                                                  self.E_calibr))/ self.E_calibr > self.E_eps) or
			                      (np.abs(self.calc_number_of_particles_XY(opt.x[:self.N_wells].reshape(self.N_tuple),
			                                                               opt.x[self.N_wells:].reshape(self.N_tuple))/self.N_part) > 0.01)):
			np.random.seed()
			x0new = zero_app + 1.0 * np.random.randn(zero_app.shape[0])
			opt = minimize(fun, x0new,
		               bounds=[(xi - 10.0 * delta, xi + 10.0 * delta) for xi in bnds],
		               options={'ftol':self.FTOL})
			col += 1
		x1 = opt.x[:self.N_wells].reshape(self.N_tuple)
		y1 = opt.x[self.N_wells:].reshape(self.N_tuple)
		if np.abs(self.calc_energy_XY(x1, y1, self.E_calibr) / self.E_calibr) > self.E_eps:
			self.make_exception('Could not find a new initial on-shell state\n')
		if np.abs((self.calc_number_of_particles_XY(x1,y1)) / self.N_part) > 0.01:
			self.make_exception('Could not find a new initial state with the same number of particles\n')
		# if np.abs(self.calc_traj_shift_XY(x1,y1, x0, y0) / delta) < 0.3:
		# 	self.make_exception('Could not find a trajectory on such a distance\n')
		# 	return x1, y1, 1
		if col == 10:
			self.make_exception('Exceeded number of attempts in E_const_perturbation\n')
			return x1, y1, 1
		else:
			return x1, y1, 0