import tensorflow as tf
import math
import numpy as np
import copy


class convLayer(object):
    def __init__(self, name, input_size, filter_dimension, stride_length, activation_function, initializer, reshape=False, batchnorm=False):
        self.name = name
        self.filter_dimension = filter_dimension
        self.__stride_length = stride_length
        self.__activation_function = activation_function
        self.__initializer = initializer
        self.input_size = input_size
        self.__reshape = reshape

        if reshape:
            self.input_size = [input_size[0], 1, 1, self.input_size[1]]

        self.output_size = copy.deepcopy(self.input_size)

        padding = 2*(math.floor(filter_dimension[0] / 2))
        self.output_size[1] = int((self.output_size[1] - filter_dimension[0] + padding) / stride_length + 1)
        padding = 2 * (math.floor(filter_dimension[1] / 2))
        self.output_size[2] = int((self.output_size[2] - filter_dimension[1] + padding) / stride_length + 1)
        self.output_size[-1] = filter_dimension[-1]

        if batchnorm:
            self.__bn_layer = batchNormLayer(self.name + '_bn', self.output_size)
        else:
            self.__bn_layer = None

    def add_to_graph(self, graph):
        with graph.as_default():
            if self.__initializer == 'xavier':
                self.weights = tf.compat.v1.get_variable(self.name + '_weights',
                                               shape=self.filter_dimension,
                                               initializer=tf.compat.v1.keras.initializers.VarianceScaling(scale=1.0, mode="fan_avg", distribution="uniform"))
            else:
                self.weights = tf.compat.v1.get_variable(self.name + '_weights',
                                               shape=self.filter_dimension,
                                               initializer=tf.compat.v1.truncated_normal_initializer(stddev=5e-2),
                                               dtype=tf.float32)

            self.biases = tf.compat.v1.get_variable(self.name + '_bias',
                                          [self.filter_dimension[-1]],
                                          initializer=tf.compat.v1.constant_initializer(0.1),
                                          dtype=tf.float32)

        if self.__bn_layer is not None:
            self.__bn_layer.add_to_graph(graph)

    def forward_pass(self, x, deterministic):
        if self.__reshape:
            x = tf.expand_dims(tf.expand_dims(x, 1), 1)

        # For convention, just use a symmetrical stride with same padding
        activations = tf.nn.conv2d(input=x, filters=self.weights,
                                   strides=[1, self.__stride_length, self.__stride_length, 1],
                                   padding='SAME')

        activations = tf.nn.bias_add(activations, self.biases)

        # Apply batchnorm if necessary
        if self.__bn_layer is not None:
            activations = self.__bn_layer.forward_pass(activations, deterministic=deterministic)

        # Apply a non-linearity specified by the user
        if self.__activation_function == 'relu':
            activations = tf.nn.relu(activations)
        elif self.__activation_function == 'tanh':
            activations = tf.tanh(activations)
        elif self.__activation_function == 'sigmoid':
            activations = tf.sigmoid(activations)

        self.activations = activations

        return activations


class poolingLayer(object):
    def __init__(self, input_size, kernel_size, stride_length, pooling_type='max'):
        self.__kernel_size = kernel_size
        self.__stride_length = stride_length
        self.input_size = input_size
        self.pooling_type = pooling_type

        # The pooling operation will reduce the width and height dimensions
        self.output_size = self.input_size

        self.output_size[1] = int(math.ceil(self.output_size[1] / float(stride_length)))
        self.output_size[2] = int(math.ceil(self.output_size[2] / float(stride_length)))

    def forward_pass(self, x, deterministic):
        if self.pooling_type == 'max':
            return tf.nn.max_pool2d(input=x,
                                  ksize=[1, self.__kernel_size, self.__kernel_size, 1],
                                  strides=[1, self.__stride_length, self.__stride_length, 1],
                                  padding='SAME')
        elif self.pooling_type == 'avg':
            return tf.nn.avg_pool2d(input=x,
                                  ksize=[1, self.__kernel_size, self.__kernel_size, 1],
                                  strides=[1, self.__stride_length, self.__stride_length, 1],
                                  padding='SAME')


class fullyConnectedLayer(object):
    def __init__(self, name, input_size, output_size, reshape, batch_size, activation_function, initializer, regularization_coefficient):
        self.name = name
        self.input_size = input_size
        #self.output_size = output_size
        self.output_size = [batch_size, output_size]
        self.__reshape = reshape
        self.__batch_size = batch_size
        self.__activation_function = activation_function
        self.__initializer = initializer
        self.regularization_coefficient = regularization_coefficient

    def add_to_graph(self, graph):
        with graph.as_default():
            # compute the vectorized size for weights if we will need to reshape it
            if self.__reshape:
                vec_size = self.input_size[1] * self.input_size[2] * self.input_size[3]
            else:
                vec_size = self.input_size[1]

            if self.__initializer == 'xavier':
                self.weights = tf.compat.v1.get_variable(self.name + '_weights', shape=[vec_size, self.output_size[-1]],
                                               initializer=tf.compat.v1.keras.initializers.VarianceScaling(scale=1.0, mode="fan_avg", distribution="uniform"))
            else:
                self.weights = tf.compat.v1.get_variable(self.name + '_weights',
                                               shape=[vec_size, self.output_size[-1]],
                                               initializer=tf.compat.v1.truncated_normal_initializer(stddev=math.sqrt(2.0 / self.output_size)),
                                               dtype=tf.float32)

            self.biases = tf.compat.v1.get_variable(self.name + '_bias',
                                          self.output_size[-1],
                                          initializer=tf.compat.v1.constant_initializer(0.1),
                                          dtype=tf.float32)

    def forward_pass(self, x, deterministic):
        # Reshape into a column vector if necessary
        if self.__reshape is True:
            x = tf.reshape(x, [-1, np.prod(self.input_size[1:])])

        activations = tf.matmul(x, self.weights)
        activations = tf.add(activations, self.biases)

        # Apply a non-linearity specified by the user
        if self.__activation_function == 'relu':
            activations = tf.nn.relu(activations)
        elif self.__activation_function == 'tanh':
            activations = tf.tanh(activations)

        self.activations = activations

        return activations


class inputLayer(object):
    """An object representing the input layer so it can give information about input size to the next layer"""
    def __init__(self, input_size, reshape=False):
        self.input_size = input_size
        self.output_size = input_size
        self.__reshape = reshape

    def forward_pass(self, x, deterministic):
        if self.__reshape:
            if len(x.shape) < 2:
                x = tf.expand_dims(x, 0)

            x = tf.expand_dims(tf.expand_dims(x, 1), 1)

        return x


class dropoutLayer(object):
    """Layer which performs dropout"""
    def __init__(self, input_size, p):
        self.input_size = input_size
        self.output_size = input_size
        self.p = p

    def forward_pass(self, x, deterministic):
        if deterministic:
            return x
        else:
            return tf.nn.dropout(x, 1 - (self.p))


class batchNormLayer(object):
    """Batch normalization layer"""
    __epsilon = 1e-3
    __decay = 0.9
    __layer = None

    def __init__(self, name, input_size):
        self.input_size = input_size
        self.output_size = input_size
        self.name = name

    def add_to_graph(self, graph):
        with graph.as_default():
            self.__layer = tf.keras.layers.BatchNormalization()

    def forward_pass(self, x, deterministic):
        x = self.__layer.apply(x, training=True)

        return x


class skipConnection(object):
    """Makes a skip connection"""
    def __init__(self, name, input_size, downsampled):
        self.name = name
        self.input_size = input_size
        self.output_size = input_size
        self.downsampled = downsampled

        if downsampled:
            filters = self.input_size[-1]

            self.layer = convLayer(self.name + 'downsample',
                                   self.input_size,
                                   [1, 1, filters / 2, filters],
                                   2,
                                   None,
                                   'xavier',
                                   False,
                                   False)

    def add_to_graph(self, graph):
        with graph.as_default():
            if self.downsampled:
                self.layer.add_to_graph(graph)

    def forward_pass(self, x, deterministic):
        if self.downsampled:
            return self.layer.forward_pass(x, deterministic)
        else:
            return x


class upsampleLayer(object):
    def __init__(self, name, input_size, filter_size, num_filters, upscale_factor, activation_function, initializer):
        self.name = name
        self.__activation_function = activation_function
        self.initializer = initializer
        self.input_size = input_size
        #self.strides = [1, upscale_factor, upscale_factor, 1]
        self.strides = [0, upscale_factor, upscale_factor, 0]
        self.upscale_factor = upscale_factor
        #self.batch_multiplier = batch_multiplier
        #self.regularization_coefficient = regularization_coefficient

        # if upscale_factor is an int then height and width are scaled the same
        if isinstance(upscale_factor, int):
            self.strides = [1, upscale_factor, upscale_factor, 1]
            h = self.input_size[1] * upscale_factor
            w = self.input_size[2] * upscale_factor
        else:  # otherwise scaled individually
            self.strides = [1, upscale_factor[0], upscale_factor[1], 1]
            h = self.input_size[1] * upscale_factor[0]
            w = self.input_size[2] * upscale_factor[1]

        # upsampling will have the same batch size self.input_size[0],
        # and will preserve the number of filters self.input_size[-1], (NHWC)
        self.output_size = [self.input_size[0], h, w, num_filters]

        # the shape needed to initialize weights is based on
        # filter_height x filter_width x input_depth x output_depth
        self.weights_shape = [filter_size, filter_size, input_size[-1], num_filters]

    def add_to_graph(self, graph):
        with graph.as_default():
            if self.initializer == 'xavier':
                self.weights = tf.compat.v1.get_variable(self.name + '_weights',
                                               shape=self.weights_shape,
                                               initializer=tf.compat.v1.keras.initializers.VarianceScaling(scale=1.0, mode="fan_avg", distribution="uniform"))
            else:
                self.weights = tf.compat.v1.get_variable(self.name + '_weights',
                                               shape=self.weights_shape,
                                               initializer=tf.compat.v1.truncated_normal_initializer(stddev=5e-2),
                                               dtype=tf.float32)

            self.biases = tf.compat.v1.get_variable(self.name + '_bias',
                                          [self.weights_shape[-1]],
                                          initializer=tf.compat.v1.constant_initializer(0.1),
                                          dtype=tf.float32)

    def forward_pass(self, x, deterministic):
        # upsampling will have the same batch size (first dimension of x),
        # and will preserve the number of filters (self.input_size[-1]), (this is NHWC)
        dyn_input_shape = tf.shape(input=x)
        batch_size = dyn_input_shape[0]
        h = dyn_input_shape[1] * self.upscale_factor
        w = dyn_input_shape[2] * self.upscale_factor
        output_shape = tf.stack([batch_size, h, w, self.weights_shape[-1]])

        activations = tf.nn.conv2d_transpose(x, self.weights, output_shape=output_shape,
                                             strides=self.strides, padding='SAME')
        activations = tf.nn.bias_add(activations, self.biases)

        # Apply a non-linearity specified by the user
        if self.__activation_function == 'relu':
            activations = tf.nn.relu(activations)
        elif self.__activation_function == 'tanh':
            activations = tf.tanh(activations)
        elif self.__activation_function == 'lrelu':
            activations = tf.nn.leaky_relu(activations)
        elif self.__activation_function == 'selu':
            activations = tf.nn.selu(activations)

        self.activations = activations

        if activations.shape[-1] == 1:
            return tf.squeeze(activations)
        else:
            return activations
