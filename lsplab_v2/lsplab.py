from . import biotools
from . import cnn
from . import lstm
from . import plotter
from . import reporter
from . import timer
from . import layers

import tensorflow as tf
import numpy as np
import pandas as pd
from tqdm import trange
import emoji
import saliency
from PIL import Image
import matplotlib.pyplot as plt

import datetime
import math
import os
import glob
import time
import shutil


class lsp(object):
    # Options
    __debug = False
    __reporter = reporter.reporter()
    __batch_size = None
    __report_rate = None
    __decoder_activation = 'linear'
    __image_depth = 3
    __num_fold_restarts = 10
    __num_failed_attempts = 0
    __mode = 'longitudinal'
    __random_seed = None
    __use_batchnorm = True
    __downsample_mod = 1

    __num_folds = None

    __pretraining_batches = None
    __training_batches = None
    __cache_files = []

    __major_queue_capacity = 64

    __main_lr = 0.001
    __decoder_lr = 0.0001
    __global_weight_decay = 0.0001
    __global_reg = 0.0005
    __variance_constant = 0.2
    __lstm_units = 8

    __anneal_lr = True
    __pretrain_convergence_thresh_upper = 0.5

    # Image options stuff
    __do_augmentation = False
    __do_crop = False
    __crop_amount = 1.
    __standardize_images = True

    # Dataset info
    __num_train_samples = None
    __num_test_samples = None
    __num_timepoints = None
    __cache_filename = None
    __use_memory_cache = False
    __current_train_files = None
    __current_test_file = None

    # Graph machinery
    __session = None
    __graph = None
    __coord = None
    __threads = None
    __num_gpus = 1
    __num_threads = 4

    # Graph components
    __input_batch_train = None
    __inorder_input_batch_train = None

    # Subgraph objects
    feature_extractor = None
    lstm = None
    __decoder_net = None
    __n = 16
    __decoder_iterations = 10000
    __geodesic_path_iterations = 300
    __target_vertices = 30

    # Tensorboard stuff
    __pretraining_summaries = None
    __decoder_summaries = None
    __training_summaries = None
    __tb_writer = None
    __tb_file = None
    results_path = None

    # Results
    __all_projections = []
    __geo_pheno = []
    __total_treated_skipped = 0
    __global_timer = None
    __reporting_chunks = None

    def __init__(self, debug, batch_size=8):
        self.__debug = debug
        self.__batch_size = batch_size
        self.__global_timer = timer.timer()
        self.__total_treated_skipped = 0

    def __log(self, message):
        if self.__debug:
            print(('{0}: {1}'.format(datetime.datetime.now().strftime("%I:%M%p"), message.encode('utf-8'))))

    def __initialize(self):
        self.__log('Initializing variables...')

        with self.__graph.as_default():
            if self.__random_seed is not None:
                tf.compat.v1.set_random_seed(self.__random_seed)

            self.__session.run(tf.compat.v1.global_variables_initializer())
            self.__session.run(tf.compat.v1.local_variables_initializer())
            self.__session.run(self.__queue_init_ops)

    def __shutdown(self):
        self.__log('Shutting down...')
        self.__session.close()

        self.__graph = None
        self.__session = None

        if self.__use_memory_cache is False:
            self.__log('Removing cache files...')

            for file in self.__cache_files:
                for filename in glob.glob('/tmp/{0}*'.format(file)):
                    os.remove(filename)

            self.__cache_files = []

    def __reset_graph(self):
        # Reset all graph elements
        self.__graph = tf.Graph()
        self.__session = tf.compat.v1.Session(graph=self.__graph)

    def set_random_seed(self, seed):
        self.__random_seed = seed

    def report_by_chunks(self, chunks):
        self.__reporting_chunks = chunks

    def set_use_batchnorm(self, use_batchnorm):
        self.__use_batchnorm = use_batchnorm

    def save_state(self, directory=None):
        """Save all trainable variables as a checkpoint in the current working path"""
        self.__log('Saving parameters...')

        if directory is None:
            dir = './saved_state'
        else:
            dir = os.path.join(directory, 'saved_state')

        self.__make_directory(dir)

        with self.__graph.as_default():
            saver = tf.compat.v1.train.Saver(tf.compat.v1.trainable_variables())
            saver.save(self.__session, dir + '/tfhSaved')

    def load_state(self, directory='./saved_state'):
        """
        Load all trainable variables from a checkpoint file specified from the load_from_saved parameter in the
        class constructor.
        """
        self.__log('Loading from checkpoint file...')

        with self.__graph.as_default():
            saver = tf.compat.v1.train.Saver(tf.compat.v1.trainable_variables())
            saver.restore(self.__session, tf.train.latest_checkpoint(directory))

    def __save_decoder(self):
        """Save all trainable variables as a checkpoint in the current working path"""
        self.__log('Saving decoder...')

        dir = os.path.join(self.results_path, 'decoder_vars', 'decoder_vars')

        with self.__graph.as_default():
            saver = tf.compat.v1.train.Saver(tf.compat.v1.get_collection(tf.compat.v1.GraphKeys.GLOBAL_VARIABLES, scope='decoder'))
            saver.save(self.__session, dir)

    def __load_decoder(self):
        """Save all trainable variables as a checkpoint in the current working path"""
        self.__log('Loading decoder...')

        directory = os.path.join(self.results_path, 'decoder_vars')

        with self.__graph.as_default():
            saver = tf.compat.v1.train.Saver(tf.compat.v1.get_collection(tf.compat.v1.GraphKeys.GLOBAL_VARIABLES, scope='decoder'))
            saver.restore(self.__session, tf.train.latest_checkpoint(directory))

    def use_downsampling(self, mod):
        self.__downsample_mod = mod

    def __save_embeddings(self):
        def save_metadata(batch_ys, metadata_path):
            with open(metadata_path, 'w') as f:
                f.write("Index\tLabel\n")
                for index, label in enumerate(batch_ys):
                    if type(label) is int:
                        f.write("%d\t%d\n" % (index, label))
                    else:
                        f.write('\t'.join((str(index), str(label))) + '\n')

        self.__log('Saving tensorboard projections...')

        labels = []
        feats = []

        for timepoint in self.__all_projections:
            for datapoint in timepoint:
                labels.append(int(datapoint[1]))
                feats.append(datapoint[2])

        labels = np.array(labels)
        feats = np.array(feats)

        config = tf.contrib.tensorboard.plugins.projector.ProjectorConfig()
        metadata_path = os.path.join(self.__tb_file, 'metadata.tsv')

        save_metadata(labels, metadata_path)

        emb = tf.Variable(feats, name='embeddings', trainable=False)
        embedding = config.embeddings.add()
        embedding.tensor_name = emb.name
        embedding.metadata_path = metadata_path

        tf.contrib.tensorboard.plugins.projector.visualize_embeddings(self.__tb_writer, config)

        saver = tf.compat.v1.train.Saver(max_to_keep=1)
        self.__session.run(emb.initializer)
        saver.save(self.__session, os.path.join(self.__tb_file, 'ckpt'))

    def __save_as_image(self, mat, path):
        plt.clf()
        plt.imshow(mat, cmap='gray', vmin=0., vmax=1.)
        plt.savefig(path)

    def load_records(self, records_path, image_height, image_width, num_timepoints, image_depth=3):
        """Load records created from the dataset"""
        self.__record_files = [os.path.join(records_path, f) for f in os.listdir(records_path) if
                        os.path.isfile(os.path.join(records_path, f)) and not f.endswith('.csv')]

        self.__image_height = image_height
        self.__image_width = image_width
        self.__image_depth = image_depth
        self.__num_timepoints = num_timepoints

    def set_n(self, new_n):
        self.__n = new_n

    def set_augmentation(self, aug):
        self.__do_augmentation = aug

    def set_cropping_augmentation(self, do_crop, crop_amount=0.85):
        self.__do_crop = do_crop
        self.__crop_amount = crop_amount

    def set_standardize_images(self, standardize):
        self.__standardize_images = standardize

    def set_num_path_vertices(self, n):
        self.__target_vertices = n

    def set_num_decoder_iterations(self, n):
        self.__decoder_iterations = n

    def set_num_path_iterations(self, n):
        self.__geodesic_path_iterations = n

    def set_use_memory_cache(self, b):
        self.__use_memory_cache = b

    def set_variance_constant(self, c):
        self.__variance_constant = c

    def set_mode(self, mode):
        if mode == 'longitudinal' or mode == 'cross sectional':
            self.__mode = mode
        else:
            self.__log('Invalid mode set, must be longitudinal or cross sectional.')
            exit()

    def __initialize_data(self):
        # Input pipelines for training

        self.__input_batch_train, init_op_1, cache_file_path = \
            biotools.get_sample_from_tfrecords_shuffled(self.__current_train_files,
                                                        self.__batch_size,
                                                        self.__image_height,
                                                        self.__image_width,
                                                        self.__image_depth,
                                                        self.__num_timepoints * self.__downsample_mod,
                                                        queue_capacity=self.__major_queue_capacity,
                                                        num_threads=self.__num_threads,
                                                        cached=True,
                                                        in_memory=self.__use_memory_cache,
                                                        mod=self.__downsample_mod)

        self.__cache_files.append(cache_file_path)

        # Input pipelines for testing
        self.__input_batch_test, init_op_2, cache_file_path = \
            biotools.get_sample_from_tfrecords_shuffled(self.__current_test_file,
                                                        self.__batch_size,
                                                        self.__image_height,
                                                        self.__image_width,
                                                        self.__image_depth,
                                                        self.__num_timepoints * self.__downsample_mod,
                                                        queue_capacity=self.__major_queue_capacity,
                                                        num_threads=self.__num_threads,
                                                        cached=True,
                                                        in_memory=self.__use_memory_cache,
                                                        mod=self.__downsample_mod)

        self.__cache_files.append(cache_file_path)

        self.__queue_init_ops = [init_op_1, init_op_2]

    def __get_num_records(self, records_path):
        self.__log('Counting records in {0}...'.format(records_path))
        return sum(1 for _ in tf.compat.v1.python_io.tf_record_iterator(records_path))

    def __resize_image(self, x):
        resized_height = int(self.__image_height * self.__crop_amount)
        resized_width = int(self.__image_width * self.__crop_amount)

        with self.__graph.device('/cpu:0'):
            image = tf.image.resize_with_crop_or_pad(x, resized_height, resized_width)

        return image

    def __apply_augmentations(self, image, resized_height, resized_width):
        with self.__graph.device('/cpu:0'):
            if self.__do_augmentation:
                image = tf.image.random_brightness(image, max_delta=0.5)
                image = tf.image.random_contrast(image, lower=0.6, upper=1.4)
                image = tf.map_fn(lambda x: tf.image.random_flip_left_right(x), image)

            if self.__do_crop:
                image = tf.map_fn(lambda x: tf.image.random_crop(x, [resized_height, resized_width, self.__image_depth]), image)

        return image

    def __apply_image_standardization(self, image, on_GPU=False):
        if self.__standardize_images:
            if on_GPU:
                def standardize(img):
                    mean, var = tf.nn.moments(x=img, axes=[0, 1, 2])
                    adjusted_stddev = tf.reduce_max(input_tensor=[tf.sqrt(var), 1.0 / tf.sqrt(tf.cast(tf.size(input=img), tf.float32))])

                    return (img - mean) / adjusted_stddev

                image = tf.map_fn(lambda x: standardize(x), image, parallel_iterations=self.__batch_size)

                return image
            else:
                with self.__graph.device('/cpu:0'):
                        image = tf.map_fn(lambda x: tf.image.per_image_standardization(x), image)

                return image
        else:
            return image

    def __with_all_datapoints(self, op, datapoint_shape, num_records):
        """Get the results of running an op for all datapoints"""
        total_batches = int(math.ceil(num_records / float(self.__batch_size)))
        remainder = (total_batches * self.__batch_size) - num_records
        outputs = np.empty(datapoint_shape)

        with self.__graph.as_default():
            for i in range(total_batches):
                batch_output = self.__session.run(op)
                batch_output = np.reshape(batch_output, [-1, datapoint_shape[1]])
                outputs = np.concatenate((outputs, batch_output), axis=0)

        outputs = np.delete(outputs, 0, axis=0)

        if remainder != 0:
            for i in range(remainder):
                outputs = np.delete(outputs, -1, axis=0)

        return outputs

    def __save_full_datapoints(self, id, treatment, processed_images, num_datapoints):
        """Gets the raw feature vector for all datapoints"""
        with self.__graph.as_default():
            all_embeddings = tf.concat(processed_images, axis=1)

            # Append treatment and genotype data
            IID = tf.expand_dims(tf.cast(id, dtype=tf.float32), axis=-1)
            treatment = tf.expand_dims(tf.cast(treatment, dtype=tf.float32), axis=-1)
            all_features = tf.concat([IID, treatment, all_embeddings], axis=1)

            feature_length = ((self.feature_extractor.get_output_size()) * len(processed_images)) + 2

            all_outputs = self.__with_all_datapoints(all_features, [1, feature_length], num_datapoints)

        temp = np.array(all_outputs)
        head = temp[:, :2]
        all_outputs_separated = [np.concatenate([head, temp[:, 2+(timestep*(self.__n)):2+((timestep+1)*(self.__n))]], axis=1) for timestep in range(len(processed_images))]

        all_projections = []

        for i in range(self.__num_timepoints):
            all_projections.append([])

        for timestep in range(len(all_outputs_separated)):
            rows = all_outputs_separated[timestep]

            # Loop through all treated entries
            for row in rows:
                # Find corresponding non-treated entries
                IID = row[0]
                treatment = row[1]
                combined_features = row[2:]

                all_projections[timestep].append((int(IID), int(treatment), combined_features))

        # Also save the full data internally for later
        for timestep in range(len(all_outputs_separated)):
            self.__all_projections[timestep].extend(all_projections[timestep])

    def __linear_loss(self, vec1, vec2):
        return tf.abs(tf.subtract(vec1, vec2))

    def __sigmoid_cross_entropy_loss(self, treatment, logits):
        """Returns sigmoid cross entropy loss"""
        return tf.nn.sigmoid_cross_entropy_with_logits(labels=treatment, logits=logits)

    def __get_treatment_loss(self, treatment, vec):
        treatment_float = tf.cast(treatment, dtype=tf.float32)
        losses = self.__sigmoid_cross_entropy_loss(treatment_float, vec)

        return tf.reduce_mean(input_tensor=losses)

    def __get_clipped_gradients(self, loss, lr, optimizer=None, vars=None):
        if optimizer is None:
            optimizer = tf.compat.v1.train.AdamOptimizer(lr)

        gvs = optimizer.compute_gradients(loss, var_list=vars)

        # Remove none gradients
        gvs = [t for t in gvs if t[0] is not None]

        capped_gvs = [(tf.clip_by_value(grad, -5., 5.), var) for grad, var in gvs]

        return capped_gvs, optimizer

    def __apply_gradients(self, optimizer, gradients):
        objective = optimizer.apply_gradients(gradients)

        return objective

    def __minimize_with_clipped_gradients(self, loss, lr, vars=None):
        capped_gvs, optimizer = self.__get_clipped_gradients(loss, lr, vars=vars)
        objective = optimizer.apply_gradients(capped_gvs)

        return objective, capped_gvs

    def __average_gradients(self, tower_grads):
        average_grads = []

        for grad_and_vars in zip(*tower_grads):
            grads = []
            for g, _ in grad_and_vars:
                expanded_g = tf.expand_dims(g, 0)
                grads.append(expanded_g)

            grad = tf.concat(axis=0, values=grads)
            grad = tf.reduce_mean(input_tensor=grad, axis=0)

            v = grad_and_vars[0][1]
            grad_and_var = (grad, v)
            average_grads.append(grad_and_var)

        return average_grads

    def __make_directory(self, path):
        if not os.path.isdir(path):
            os.mkdir(path)

    def __parse_batch(self, batch_data):
        id = batch_data['id']
        treatment = batch_data['treatment']

        image_data = []

        for i in range(self.__num_timepoints):
            data = batch_data['image_data_{0}'.format(i)]
            image_data.append(data)

        return id, treatment, image_data

    def __build_convnet(self):
        # Define the structure of the CNN used for feature extraction
        self.feature_extractor.add_input_layer()

        # 4-layer
        self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, self.__image_depth, 16], stride_length=1, activation_function='relu')
        self.feature_extractor.add_pooling_layer(kernel_size=3, stride_length=3)
        self.feature_extractor.add_batchnorm_layer()

        self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 16, 32], stride_length=1, activation_function='relu')
        self.feature_extractor.add_pooling_layer(kernel_size=3, stride_length=3)
        self.feature_extractor.add_batchnorm_layer()

        self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 32, 32], stride_length=1, activation_function='relu')
        self.feature_extractor.add_pooling_layer(kernel_size=3, stride_length=3)
        self.feature_extractor.add_batchnorm_layer()

        self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 32, 32], stride_length=1, activation_function='relu')
        self.feature_extractor.add_pooling_layer(kernel_size=3, stride_length=2)
        self.feature_extractor.add_batchnorm_layer()

        # vgg-16
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, self.__image_depth, 64], stride_length=1, activation_function='relu')
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 64, 64], stride_length=1, activation_function='relu')
        # self.feature_extractor.add_pooling_layer(kernel_size=2, stride_length=2)
        # self.feature_extractor.add_batchnorm_layer()
        #
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 64, 128], stride_length=1, activation_function='relu')
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 128, 128], stride_length=1, activation_function='relu')
        # self.feature_extractor.add_pooling_layer(kernel_size=2, stride_length=2)
        # self.feature_extractor.add_batchnorm_layer()
        #
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 128, 256], stride_length=1, activation_function='relu')
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 256, 256], stride_length=1, activation_function='relu')
        # self.feature_extractor.add_pooling_layer(kernel_size=2, stride_length=2)
        # self.feature_extractor.add_batchnorm_layer()
        #
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 256, 512], stride_length=1, activation_function='relu')
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 512, 512], stride_length=1, activation_function='relu')
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 512, 512], stride_length=1, activation_function='relu')
        # self.feature_extractor.add_pooling_layer(kernel_size=2, stride_length=2)
        # self.feature_extractor.add_batchnorm_layer()
        #
        # self.feature_extractor.add_skip_connection()
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 512, 512], stride_length=1, activation_function='relu')
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 512, 512], stride_length=1, activation_function='relu')
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 512, 512], stride_length=1, activation_function='relu')
        # self.feature_extractor.add_pooling_layer(kernel_size=2, stride_length=2)
        # self.feature_extractor.add_batchnorm_layer()

        # resnet-7
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[7, 7, self.__image_depth, 64], stride_length=2, activation_function='relu', batchnorm=True)
        # self.feature_extractor.add_pooling_layer(kernel_size=3, stride_length=2)
        #
        # self.feature_extractor.add_skip_connection()
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 64, 64], stride_length=1, activation_function='relu', batchnorm=True)
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 64, 128], stride_length=2, activation_function='relu', batchnorm=True)
        # self.feature_extractor.add_skip_connection(downsampled=True)
        #
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 128, 128], stride_length=1, activation_function='relu', batchnorm=True)
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 128, 256], stride_length=2, activation_function='relu', batchnorm=True)
        # self.feature_extractor.add_skip_connection(downsampled=True)
        #
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 256, 256], stride_length=1, activation_function='relu', batchnorm=True)
        # self.feature_extractor.add_convolutional_layer(filter_dimension=[3, 3, 256, 512], stride_length=2, activation_function='relu', batchnorm=True)
        # self.feature_extractor.add_skip_connection(downsampled=True)

        self.feature_extractor.add_fully_connected_layer(output_size=64, activation_function='relu', regularization_coefficient=self.__global_reg)
        self.feature_extractor.add_output_layer(output_size=self.__n, activation_function=None, regularization_coefficient=self.__global_reg)

    def __build_decoder(self):
        self.__decoder_net.add_input_layer(reshape=True)

        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, self.__n, 16], stride_length=1, activation_function='relu')
        self.__decoder_net.add_upsampling_layer(filter_size=3, num_filters=16, upscale_factor=2, activation_function='relu')

        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 16, 32], stride_length=1, activation_function='relu')
        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 32, 32], stride_length=1, activation_function='relu')
        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 32, 32], stride_length=1, activation_function='relu')
        self.__decoder_net.add_upsampling_layer(filter_size=3, num_filters=32, upscale_factor=2, activation_function='relu')

        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 32, 32], stride_length=1, activation_function='relu')
        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 32, 32], stride_length=1, activation_function='relu')
        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 32, 32], stride_length=1, activation_function='relu')
        self.__decoder_net.add_upsampling_layer(filter_size=3, num_filters=32, upscale_factor=2, activation_function='relu')

        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 32, 64], stride_length=1, activation_function='relu')
        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 64, 64], stride_length=1,  activation_function='relu')
        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 64, 64], stride_length=1, activation_function='relu')
        self.__decoder_net.add_upsampling_layer(filter_size=3, num_filters=64, upscale_factor=2, activation_function='relu')

        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 64, 64], stride_length=1, activation_function='relu')
        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 64, 64], stride_length=1, activation_function='relu')
        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 64, 64], stride_length=1, activation_function='relu')
        self.__decoder_net.add_upsampling_layer(filter_size=3, num_filters=64, upscale_factor=2, activation_function='relu')

        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 64, 32], stride_length=1, activation_function='relu')
        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 32, 32], stride_length=1, activation_function='relu')
        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 32, 16], stride_length=1, activation_function='relu')
        self.__decoder_net.add_upsampling_layer(filter_size=3, num_filters=16, upscale_factor=2, activation_function='relu')

        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 16, 16], stride_length=1, activation_function='relu')
        self.__decoder_net.add_upsampling_layer(filter_size=3, num_filters=16, upscale_factor=2, activation_function='relu')

        self.__decoder_net.add_convolutional_layer(filter_dimension=[3, 3, 16, 16], stride_length=1, activation_function='relu')
        self.__decoder_net.add_upsampling_layer(filter_size=3, num_filters=16, upscale_factor=2, activation_function='relu')

        if self.__decoder_activation == 'tanh':
            self.__decoder_net.add_convolutional_layer(filter_dimension=[1, 1, 16, self.__image_depth], stride_length=1, activation_function='tanh')
        elif self.__decoder_activation == 'relu':
            self.__decoder_net.add_convolutional_layer(filter_dimension=[1, 1, 16, self.__image_depth], stride_length=1, activation_function='relu')
        elif self.__decoder_activation == 'sigmoid':
            self.__decoder_net.add_convolutional_layer(filter_dimension=[1, 1, 16, self.__image_depth], stride_length=1, activation_function='sigmoid')
        else:
            self.__decoder_net.add_convolutional_layer(filter_dimension=[1, 1, 16, self.__image_depth], stride_length=1, activation_function=None)

    def __build_geodesic_graph(self):
        self.__geodesic_path_lengths = []
        self.__geodesic_chunk_lengths = []
        self.__geodesic_optimizers = []
        self.__geodesic_interpolated_points = []
        self.__geodesic_objectives = []
        self.__geodesic_distance_totals = []

        self.__geodesic_placeholder_A = []
        self.__geodesic_placeholder_B = []
        self.__geodesic_anchor_points = []

        # Calculate how many interpolated vertices we will need
        if self.__mode == 'longitudinal':
            self.__geodesic_num_interpolations = int((self.__target_vertices - self.__num_timepoints) / (self.__num_timepoints -1))
            total_vertices = self.__num_timepoints + (self.__geodesic_num_interpolations * (self.__num_timepoints - 1))
        elif self.__mode == 'cross sectional':
            self.__geodesic_num_interpolations = self.__target_vertices - 2
            total_vertices = self.__target_vertices

        if self.__reporting_chunks is None:
            self.__reporting_chunks = [[0, total_vertices - 1]]

        # Assemble a graph
        for d in range(self.__num_gpus):
            with tf.device('/device:GPU:{0}'.format(d)):
                with tf.compat.v1.name_scope('gpu_%d_' % (d)) as scope:
                    def decoded_L2_distance(embedding_A, embedding_B):
                        return tf.norm(tensor=tf.subtract(self.__decoder_net.forward_pass(embedding_A),
                                                   self.__decoder_net.forward_pass(embedding_B)))

                    # Make static placeholders for the start, end, and all anchors in between
                    start_point = tf.compat.v1.placeholder(tf.float32, shape=(self.__n))
                    end_point = tf.compat.v1.placeholder(tf.float32, shape=(self.__n))

                    self.__geodesic_placeholder_A.append(start_point)
                    self.__geodesic_placeholder_B.append(end_point)

                    if self.__mode == 'longitudinal':
                        anchor_points = [tf.compat.v1.placeholder(tf.float32, shape=(self.__n)) for i in range(self.__num_timepoints - 2)]
                        self.__geodesic_anchor_points.append(anchor_points)

                        if self.__geodesic_num_interpolations > 0:
                            interpolated_points = [tf.Variable(tf.zeros([self.__n]), name='intermediate-%d' % x) for x in range(self.__geodesic_num_interpolations * (self.__num_timepoints - 1))]
                    elif self.__mode == 'cross sectional':
                        interpolated_points = [tf.Variable(tf.zeros([self.__n]), name='intermediate-%d' % x) for x in range(self.__geodesic_num_interpolations)]

                    if self.__geodesic_num_interpolations > 0:
                        self.__geodesic_interpolated_points.append(interpolated_points)

                    # Build the list of distances (losses) between points
                    previous_node = [start_point]
                    next_node = [None]
                    next_anchor = 0
                    next_interpolated = 0

                    intermediate_distances = []

                    for i in range(1, total_vertices):
                        if i == total_vertices - 1:
                            # Distance to end point
                            next_node[0] = end_point
                        elif i % (self.__geodesic_num_interpolations + 1) == 0:
                            # Distance to an anchor point
                            next_node[0] = anchor_points[next_anchor]
                            next_anchor = next_anchor + 1
                        else:
                            # Distance to an interpolated point
                            next_node[0] = interpolated_points[next_interpolated]
                            next_interpolated = next_interpolated + 1

                        intermediate_distances.append(decoded_L2_distance(previous_node[0], next_node[0]))

                        previous_node[0] = next_node[0]

                    total_path_length = tf.reduce_sum(input_tensor=intermediate_distances)
                    self.__geodesic_path_lengths.append(total_path_length)

                    self.__geodesic_chunk_lengths.append([tf.reduce_sum(input_tensor=intermediate_distances[chunk[0]:chunk[1]]) for chunk in self.__reporting_chunks])

                    if self.__geodesic_num_interpolations > 0:
                        ms_dist = tf.reduce_mean(input_tensor=tf.square(intermediate_distances))

                        gradients, optimizer = self.__get_clipped_gradients(ms_dist, self.__main_lr, vars=interpolated_points)
                        self.__geodesic_optimizers.append(optimizer)
                        self.__geodesic_objectives.append(self.__apply_gradients(optimizer, gradients))

        if self.__geodesic_num_interpolations > 0:
            # Collect all of the optimizer variables we have to re-inititalize
            optimizer_vars = []
            intermediate_vars = []

            for x in self.__geodesic_optimizers:
                optimizer_vars.extend(x.variables())

            for x in self.__geodesic_interpolated_points:
                intermediate_vars.extend(x)

            self.__geodesic_init_ops = [tf.compat.v1.variables_initializer(var_list=intermediate_vars),
                                        tf.compat.v1.variables_initializer(var_list=optimizer_vars)]

            # Graph ops for generating the interpolation image sequence by decoding the intermediate points
            self.__geodesic_decoded_intermediate = [[self.__decoder_net.forward_pass(x) for x in d] for d in self.__geodesic_interpolated_points]

    def __geodesic_distance(self, series, t):
        '''Gets the geodesic distance for a series of points, can do n pairs in parallel where n is the number of gpus'''

        series = np.array(series)

        starts = series[:, 0, :]
        ends = series[:, -1, :]

        # Build the point placeholders for start and end points
        fd = {}

        if self.__mode == 'longitudinal':
            anchors = series[:, 1:-1, :]

            # Build the point placeholders for anchor points
            for (x, y) in zip(self.__geodesic_anchor_points, anchors):
                for a, b in zip(x, y):
                    fd[a] = b

        for (x, y) in zip(self.__geodesic_placeholder_A, starts):
            fd[x] = y

        for (x, y) in zip(self.__geodesic_placeholder_B, ends):
            fd[x] = y

        if self.__geodesic_num_interpolations > 0:
            self.__session.run(self.__geodesic_init_ops, feed_dict=fd)

            # Assign the interpolated points to a linear interpolation
            def get_midpoints(point_A, point_B):
                eps = (point_B - point_A) / self.__geodesic_num_interpolations
                return [np.add(point_A, eps * x) for x in range(1, self.__geodesic_num_interpolations + 1)]

            midpoints = []

            for d in range(self.__num_gpus):
                mps = []

                if self.__mode == 'longitudinal':
                    mps.extend(get_midpoints(starts[d], anchors[d][0]))

                    for i in range(len(anchors[d]) - 1):
                        mps.extend(get_midpoints(anchors[d][i], anchors[d][i + 1]))

                    mps.extend(get_midpoints(anchors[d][-1], ends[d]))

                    midpoints.append(mps)
                elif self.__mode == 'cross sectional':
                    mps.extend(get_midpoints(starts[d], ends[d]))

                    midpoints.append(mps)

            for d in range(0, self.__num_gpus):
                for j in range(0, len(midpoints[d])):
                       self.__geodesic_interpolated_points[d][j].load(midpoints[d][j], self.__session)

            # Train the parameters
            for k in range(self.__geodesic_path_iterations):
                _, current_distance = self.__session.run([self.__geodesic_objectives, self.__geodesic_path_lengths], feed_dict=fd)
                t.set_description('Path distance: {0}'.format(current_distance))
                t.refresh()

        # Get final distance
        # QQ
        dists = self.__session.run(self.__geodesic_chunk_lengths, feed_dict=fd)
        # dists, points = self.__session.run([self.__geodesic_chunk_lengths, self.__geodesic_anchor_points], feed_dict=fd)
        # import random
        #
        # for a, b, c in zip(starts, anchors, ends):
        #    combined = np.vstack([a, b, c])
        #
        #    # Plot path plot
        #    rand_int = str(random.randint(1, 10000))
        #    # plotter.plot_path(os.path.join(self.results_path, 'path_plots'), rand_int, combined)
        #
        #    # Generate image sequence
        #    self.__make_directory(os.path.join(self.results_path, 'interpolations'))
        #
        #    decoder_output = self.__session.run(self.__geodesic_decoded_intermediate[0])
        #
        #    for i, generated in enumerate(decoder_output):
        #        self.__save_as_image(np.squeeze(generated), os.path.join(self.results_path, 'interpolations', '{0}-{1}.png'.format(rand_int, i)))

        return dists

    def __get_geodesics_for_all_projections(self):
        def get_sequence_at_index(idx, projections):
            return [p[idx][2] for p in projections]

        ret = []

        if self.__mode == 'longitudinal':
            num_rows = len(self.__all_projections[0])
            all_idxs = list(range(num_rows))

            t = trange(0, num_rows, self.__num_gpus)

            for i in t:
                num_padding = 0

                if i + self.__num_gpus > num_rows:
                    idxs = all_idxs[i:]
                    num_padding = len(all_idxs) % self.__num_gpus
                    idxs.extend(([all_idxs[0]] * num_padding))
                else:
                    idxs = all_idxs[i:i+self.__num_gpus]

                if idxs is None:
                    break

                series = []
                meta = []

                for idx in idxs:
                    series.append(get_sequence_at_index(idx, self.__all_projections))
                    meta.append(self.__all_projections[0][idx][:2])

                # These are dummies, we won't use the results
                for j in range(num_padding):
                    series.append(get_sequence_at_index(0, self.__all_projections))

                # Do the evaluation
                dists = self.__geodesic_distance(series, t)

                r = [[metadata[0], metadata[1], dist] for metadata, dist in zip(meta, dists)]

                ret.extend(r)
        elif self.__mode == 'cross sectional':
            def get_projections_with_treatment(tr):
                return [[x for x in p if x[1] == tr] for p in self.__all_projections]

            def get_idx_for_accid(accid, projections):
                for p in range(len(projections[0])):
                    if projections[0][p][0] == accid:
                        return p

                return None

            treated_projections = get_projections_with_treatment(1)
            untreated_projections = get_projections_with_treatment(0)

            # Remove all treated with no corresponding untreated
            treated_projections = [[x for x in p if get_idx_for_accid(x[0], untreated_projections) is not None] for p in treated_projections]

            num_rows = len(treated_projections[0])
            all_idxs = list(range(num_rows))

            t = trange(0, num_rows, self.__num_gpus)

            for i in t:
                num_padding = 0

                if i + self.__num_gpus > num_rows:
                    idxs = all_idxs[i:]
                    num_padding = len(all_idxs) % self.__num_gpus
                    idxs.extend(([all_idxs[0]] * num_padding))
                else:
                    idxs = all_idxs[i:i + self.__num_gpus]

                if idxs is None:
                    break

                series = []
                meta = []

                for idx in idxs:
                    accid = treated_projections[0][idx][0]
                    treated_point = treated_projections[-1][idx][2]
                    untreated_idx = get_idx_for_accid(accid, untreated_projections)

                    untreated_point = untreated_projections[-1][untreated_idx][2]

                    series.append([treated_point, untreated_point])
                    meta.append(treated_projections[0][idx][:2])

                # These are dummies, we won't use the results
                for j in range(num_padding):
                    series.append(series[-1])

                # Do the evaluation
                dists = self.__geodesic_distance(series, t)

                r = [[metadata[0], metadata[1], dist] for metadata, dist in zip(meta, dists)]

                ret.extend(r)

        return ret

    def start(self, pretraining_epochs=10, report_rate=80, name='results', tensorboard=None, ordination_vis=False, num_gpus=1, num_threads=1, saliency_target=None, decoder_vis=False):
        """Begins training"""

        self.results_path = './' + os.path.basename(name) + '-results'

        self.__report_rate = report_rate
        self.__num_gpus = num_gpus
        self.__batch_size = self.__batch_size / num_gpus
        self.__num_threads = num_threads

        if self.__downsample_mod > 1:
            self.__num_timepoints = self.__num_timepoints / self.__downsample_mod
            self.__log('Downsampling data to {0} timepoints'.format(self.__num_timepoints))

        self.__make_directory(self.results_path)

        self.__log('Using {0} GPUs and {1} CPU threads'.format(self.__num_gpus, self.__num_threads))
        self.__log('Results will be saved into {0}'.format(self.results_path))

        self.__current_test_file = self.__record_files[0]
        self.__current_train_files = [f for f in self.__record_files if f != self.__current_test_file]

        self.__num_train_samples = sum([self.__get_num_records(x) for x in self.__current_train_files])
        self.__num_test_samples = self.__get_num_records(self.__current_test_file)

        self.__log('Training samples: {0}'.format(self.__num_train_samples))
        self.__log('Testing samples: {0}'.format(self.__num_test_samples))

        self.__pretraining_batches = (self.__num_train_samples * pretraining_epochs) / (self.__batch_size * num_gpus)

        self.__log('Training to {0} batches'.format(self.__pretraining_batches))

        self.__all_projections = [[] for i in range(self.__num_timepoints)]

        if tensorboard is not None:
            self.__tb_file = os.path.join(tensorboard, '{0}'.format(name))
        else:
            self.__tb_file = None

        # Failure loop
        for current_attempt in range(self.__num_fold_restarts):
            self.__log('This is attempt {0}'.format(current_attempt))

            self.__reset_graph()

            # If this isn't the first try, delete the old tensorflow accumulator
            if tensorboard is not None and current_attempt > 0:
                shutil.rmtree(self.__tb_file)

            # Gotta add all the shit to the graph again
            with self.__graph.as_default():
                self.__initialize_data()

                with tf.compat.v1.variable_scope('pretraining'):
                    # Build the CNN for feature extraction
                    self.feature_extractor = cnn.cnn(debug=self.__debug, batch_size=self.__batch_size)

                    self.feature_extractor.set_image_dimensions(int(self.__image_height * self.__crop_amount), int(self.__image_width  * self.__crop_amount), self.__image_depth)

                    self.__build_convnet()
                    self.feature_extractor.send_ops_to_graph(self.__graph)

                    # Build the LSTM
                    self.lstm = lstm.lstm(self.__batch_size, self.__n, self.__graph)

                with tf.compat.v1.variable_scope('decoder'):
                    self.__decoder_net = cnn.cnn(debug=True, batch_size=self.__batch_size, name_prefix="decoder-")
                    self.__decoder_net.set_image_dimensions(1, 1, self.__n + 1)

                    self.__build_decoder()

                    self.__decoder_net.send_ops_to_graph(self.__graph)

                all_pretrain_gradients = []
                all_reconstruction_gradients = []

                pretrain_optimizer = tf.compat.v1.train.AdamOptimizer(self.__main_lr)
                recon_optimizer = tf.compat.v1.train.AdamOptimizer(self.__decoder_lr)

                for d in range(num_gpus):
                    with tf.device('/device:GPU:{0}'.format(d)):
                        with tf.compat.v1.name_scope('gpu_%d_' % (d)) as scope:

                            # --- Components for training ---

                            # Graph inputs
                            batch_data = self.__input_batch_train

                            id, treatment, image_data = self.__parse_batch(batch_data)

                            # Graph components for main objective
                            cnn_embeddings = []

                            resized_height = int(self.__image_height * self.__crop_amount)
                            resized_width = int(self.__image_width * self.__crop_amount)

                            # Embed the images
                            for image in image_data:
                                if self.__do_crop:
                                    image = self.__resize_image(image)

                                image = self.__apply_image_standardization(image)
                                image = self.__apply_augmentations(image, resized_height, resized_width)

                                emb = self.feature_extractor.forward_pass(image)
                                cnn_embeddings.append(emb)

                            predicted_treatment, _ = self.lstm.forward_pass(cnn_embeddings)

                            # Determinant loss
                            all_emb = tf.concat(cnn_embeddings, 0)
                            avg = tf.reduce_mean(input_tensor=all_emb, axis=0)
                            emb_centered = all_emb - avg
                            cov = tf.matmul(tf.transpose(a=emb_centered), emb_centered) / (self.__batch_size * self.__num_timepoints)

                            # Add a small epsilon to the diagonal to make sure it's invertible
                            cov = tf.linalg.set_diag(cov, (tf.linalg.diag_part(cov) + self.__variance_constant))

                            # Determinant of the covariance matrix
                            emb_cost = tf.linalg.det(cov)

                            # Treatment loss
                            treatment_loss = self.__get_treatment_loss(treatment, predicted_treatment)

                            # Regularization costs
                            cnn_reg_loss = self.feature_extractor.get_regularization_loss()
                            lstm_reg_loss = self.lstm.get_regularization_loss()

                            # Decoder takes the output from the latent space encoder and tries to reconstruct the input
                            reconstructions = [self.__decoder_net.forward_pass(emb) for emb in cnn_embeddings]
                            reconstructions_tensor = tf.concat(reconstructions, axis=0)

                            decoder_out = self.__decoder_net.layers[-1].output_size

                            original_images = tf.image.resize(tf.concat(image_data, axis=0), [decoder_out[1], decoder_out[2]])

                            # A measure of how diverse the reconstructions are
                            _, rec_var = tf.nn.moments(x=reconstructions_tensor, axes=[0, 1])
                            reconstruction_diversity = tf.reduce_mean(input_tensor=rec_var)

                            pretrain_total_loss = tf.reduce_sum(input_tensor=[treatment_loss, cnn_reg_loss, lstm_reg_loss, emb_cost])

                            pt_vars = tf.compat.v1.get_collection(tf.compat.v1.GraphKeys.TRAINABLE_VARIABLES, 'pretraining')

                            pretrain_gradients, _ = self.__get_clipped_gradients(pretrain_total_loss, None, optimizer=pretrain_optimizer, vars=pt_vars)
                            all_pretrain_gradients.append(pretrain_gradients)

                            reconstruction_losses = tf.reduce_mean(input_tensor=tf.square(tf.subtract(original_images, reconstructions_tensor)), axis=[1, 2, 3])
                            reconstruction_loss, reconstruction_var = tf.nn.moments(x=reconstruction_losses, axes=[0])

                            reconstruction_vars = tf.compat.v1.get_collection(tf.compat.v1.GraphKeys.TRAINABLE_VARIABLES, 'decoder')
                            reconstruction_gradients, _ = self.__get_clipped_gradients(reconstruction_loss, None, optimizer=recon_optimizer, vars=reconstruction_vars)

                            all_reconstruction_gradients.append(reconstruction_gradients)

                # Average gradients and apply
                if num_gpus == 1:
                    average_pretrain_gradients = all_pretrain_gradients[0]
                    average_reconstruction_gradients = all_reconstruction_gradients[0]
                else:
                    average_pretrain_gradients = self.__average_gradients(all_pretrain_gradients)
                    average_reconstruction_gradients = self.__average_gradients(all_reconstruction_gradients)

                pretrain_objective = self.__apply_gradients(pretrain_optimizer, average_pretrain_gradients)

                reconstruction_objective = self.__apply_gradients(recon_optimizer, average_reconstruction_gradients)

                # --- Components for testing and saving ---

                # Test random for monitoring test loss
                batch_data_test = self.__input_batch_test

                id_test, treatment_test, image_data_test = self.__parse_batch(batch_data_test)

                cnn_embeddings_test = []

                for image in image_data_test:
                    if self.__do_crop:
                        image = self.__resize_image(image)

                    image = self.__apply_image_standardization(image)

                    cnn_embeddings_test.append(self.feature_extractor.forward_pass(image, deterministic=True))

                predicted_treatment_test, _ = self.lstm.forward_pass(cnn_embeddings_test)

                treatment_loss_test = self.__get_treatment_loss(treatment_test, predicted_treatment_test)

                # Decoder testing
                if self.__decoder_activation == 'tanh':
                    decoder_test_vec = [(self.__decoder_net.forward_pass(p) + 1.) / 2. for p in cnn_embeddings]
                else:
                    decoder_test_vec = [self.__decoder_net.forward_pass(p) for p in cnn_embeddings]

                # Add ops for geodesic calculations
                self.__build_geodesic_graph()

                # For saliency visualization
                if saliency_target is not None:
                    saliency_image = tf.compat.v1.placeholder(tf.float32, shape=(None, self.__image_height, self.__image_width, self.__image_depth))

                    if self.__do_crop:
                        saliency_image_resized = self.__resize_image(saliency_image)
                    else:
                        saliency_image_resized = saliency_image

                    saliency_result = self.feature_extractor.forward_pass(saliency_image_resized)

                # Aggregate tensorboard summaries
                if tensorboard is not None:
                    self.__log('Creating Tensorboard summaries...')

                    tf.compat.v1.summary.scalar('pretrain/treatment_loss', treatment_loss, collections=['pretrain_summaries'])
                    tf.compat.v1.summary.scalar('pretrain/cnn_reg_loss', cnn_reg_loss, collections=['pretrain_summaries'])
                    tf.compat.v1.summary.scalar('pretrain/lstm_reg_loss', lstm_reg_loss, collections=['pretrain_summaries'])
                    tf.compat.v1.summary.scalar('pretrain/emb_cost', emb_cost, collections=['pretrain_summaries'])
                    tf.compat.v1.summary.histogram('pretrain/predicted_treatment', predicted_treatment, collections=['pretrain_summaries'])
                    [tf.compat.v1.summary.histogram('gradients/%s-gradient' % g[1].name, g[0], collections=['pretrain_summaries']) for g in average_pretrain_gradients]

                    tf.compat.v1.summary.scalar('test/treatment_loss', treatment_loss_test, collections=['pretrain_summaries'])

                    tf.compat.v1.summary.scalar('decoder/reconstruction_loss_batch_mean', reconstruction_loss, collections=['decoder_summaries'])
                    tf.compat.v1.summary.scalar('decoder/reconstruction_loss_batch_var', reconstruction_var, collections=['decoder_summaries'])
                    tf.compat.v1.summary.scalar('decoder/reconstruction_diversity', reconstruction_diversity, collections=['decoder_summaries'])
                    #tf.summary.scalar('decoder/reconstruction_treatment_loss', recon_treatment_loss, collections=['decoder_summaries'])
                    tf.compat.v1.summary.image('decoder/reconstructions', reconstructions_tensor, collections=['decoder_summaries'])

                    # Filter visualizations
                    filter_summary = self.__get_weights_as_image(self.feature_extractor.first_layer().weights)
                    tf.compat.v1.summary.image('filters/first', filter_summary, collections=['pretrain_summaries'])

                    # Summaries for each layer
                    for layer in self.feature_extractor.layers:
                        if isinstance(layer, layers.fullyConnectedLayer) or isinstance(layer, layers.convLayer):
                            tf.compat.v1.summary.histogram('weights/' + layer.name, layer.weights, collections=['pretrain_summaries'])
                            tf.compat.v1.summary.histogram('biases/' + layer.name, layer.biases, collections=['pretrain_summaries'])
                            tf.compat.v1.summary.histogram('activations/' + layer.name, layer.activations, collections=['pretrain_summaries'])

                    self.__pretraining_summaries = tf.compat.v1.summary.merge_all(key='pretrain_summaries')
                    self.__decoder_summaries = tf.compat.v1.summary.merge_all(key='decoder_summaries')
                    self.__tb_writer = tf.compat.v1.summary.FileWriter(self.__tb_file)

                # Initialize network and threads
                self.__initialize()

                # Train the encoder
                converged, pretrain_succeeded = self.__pretrain(pretrain_objective, treatment_loss, treatment_loss_test)

                self.__log('Training finished.')

                if converged and pretrain_succeeded:
                    self.__reporter.add('Pretraining fold converged', True)

                    # Train and test the decoder
                    self.__log('Training decoder...')
                    self.__train_decoder(reconstruction_objective, reconstruction_loss)

                    if decoder_vis:
                        self.__log('Testing decoder...')
                        self.__test_decoder(decoder_test_vec, image_data)

                    # Reset queues back to the start
                    self.__session.run(self.__queue_init_ops)

                    self.__log('Saving training samples...')
                    self.__save_full_datapoints(id, treatment, cnn_embeddings, self.__num_train_samples)

                    self.__log('Saving testing samples...')
                    self.__save_full_datapoints(id_test, treatment_test, cnn_embeddings_test, self.__num_test_samples)

                    self.__log('Calculating geodesic distances...')

                    # Save geodesic distances for this fold
                    self.__current_projections = self.__get_geodesics_for_all_projections()
                    self.__geo_pheno.extend(self.__current_projections)

                    # Ordination plots
                    if ordination_vis:
                        self.__log('Saving ordination plots...')
                        self.__make_directory(self.results_path + '/ordination-plots')

                        plotter.plot_general_ordination_plot(self.__all_projections,
                                                             os.path.join(self.results_path, 'ordination-plots',
                                                             'general-ordination.png'))

                    self.__log('Process complete, finishing up...')

                    # Saliency visualization
                    if saliency_target is not None:
                        self.__log('Outputting saliency figure...')

                        self.__make_directory(os.path.join(self.results_path, 'saliency'))

                        def LoadImage(file_path):
                            im = Image.open(file_path)
                            im = np.asarray(im)
                            return im / 127.5 - 1.0

                        activations = saliency_result
                        y = tf.norm(tensor=activations)

                        saliency_test_image = LoadImage(saliency_target)

                        gbp = saliency.GuidedBackprop(self.__graph, self.__session, y, saliency_image)

                        gbp_mask = gbp.GetSmoothedMask(saliency_test_image)

                        smoothgrad_mask_grayscale = saliency.VisualizeImageGrayscale(gbp_mask)

                        self.__save_as_image(smoothgrad_mask_grayscale, os.path.join(self.results_path, 'saliency', 'saliency.png'))

                    # Write to disk in .pheno format
                    for j in range(len(self.__reporting_chunks)):
                        current_geo = [[row[0], row[1], row[2][j]] for row in self.__geo_pheno]
                        df = pd.DataFrame(current_geo)
                        df.columns = ['genotype', 'treatment', 'geodesic']
                        df.to_csv(os.path.join(self.results_path, '{0}-chunk-{1}-geo.csv'.format(name, j)), sep=' ', index=False)

                    self.__log('.pheno file(s) saved.')

                    # Write a plot of output values
                    for j in range(len(self.__reporting_chunks)):
                        current_geo = [[row[0], row[1], row[2][j]] for row in self.__geo_pheno]
                        df = pd.DataFrame(current_geo)
                        df.columns = ['genotype', 'treatment', 'geodesic']

                        self.__log('Writing trait value plot...')

                        bins = np.linspace(np.amin(df['geodesic'].tolist()), np.amax(df['geodesic'].tolist()), 100)
                        treated = df.loc[df['treatment'] == 1, 'geodesic'].tolist()
                        untreated = df.loc[df['treatment'] == 0, 'geodesic'].tolist()

                        plt.clf()
                        plt.hist(treated, bins, alpha=0.5, label='treated')
                        plt.hist(untreated, bins, alpha=0.5, label='control')
                        plt.legend(loc='upper right')
                        plt.savefig(os.path.join(self.results_path, 'trait-histogram-chunk{0}.png'.format(j)))

                    # Write tensorboard projector summary
                    if self.__tb_file is not None:
                        self.__save_embeddings()

                    self.__shutdown()
                    break
                else:
                    self.__shutdown()
                    self.__reset_graph()

                    # Anneal the learning rate
                    if not converged and self.__anneal_lr:
                        self.__main_lr = self.__main_lr * 0.1
                        self.__log('Annealing learning rate to {0}'.format(self.__main_lr))

                    if current_attempt == self.__num_fold_restarts - 1:
                        self.__reporter.add('Pretraining did NOT converge', False)
                        self.__log('Pretraining failed the maximum number of times.')

                        self.__log('Could not embed, will terminate here.')
                        self.__shutdown()
                        exit()
                    else:
                        self.__log('Pretraining attempt did not succeed, will try again.')
                        self.__num_failed_attempts += 1
                        continue

        self.__log('Sanity checks:')
        self.__reporter.print_all()

        if self.__reporter.all_succeeded():
            self.__log(emoji.emojize('Everything looks like it succeeded! Check the output folder for results. :beer_mug:'))
        else:
            self.__log('One or more folds failed. Partial output was written without the full population.')

        self.__log('Run statistics:')
        self.__log('Total time elapsed: {0}'.format(self.__global_timer.elapsed()))
        self.__log('Total failed pretrain attempts: {0}'.format(self.__num_failed_attempts))
        self.__log('Total population size ultimately used: {0}'.format(len(self.__geo_pheno)))

    def __pretrain(self, pretrain_op, loss_op, test_loss_op):
        self.__log('Starting embedding learning...')

        batch_loss = None
        samples_per_sec = 0.

        # Needed for batch norm
        update_ops = tf.compat.v1.get_collection(tf.compat.v1.GraphKeys.UPDATE_OPS)
        pretrain_op = tf.group([pretrain_op, update_ops])

        t = trange(self.__pretraining_batches)

        for i in t:
            if i % self.__report_rate == 0 and i > 0:
                if self.__tb_file is not None:
                    _, batch_loss, summary = self.__session.run([pretrain_op, loss_op, self.__pretraining_summaries])
                    self.__tb_writer.add_summary(summary, i)
                    self.__tb_writer.flush()
                else:
                    _, batch_loss = self.__session.run([pretrain_op, loss_op])

                t.set_description('EMBEDDING - Batch {}: Loss {:.3f}, samples/sec: {:.2f}'.format(i, batch_loss, samples_per_sec))
                t.refresh()
            else:
                start_time = time.time()
                self.__session.run([pretrain_op])
                elapsed = time.time() - start_time
                samples_per_sec = (self.__batch_size / elapsed) * self.__num_gpus

        # Use the mean loss from 10 test batches to determine success
        train_loss = np.mean([self.__session.run(loss_op) for x in range(10)])
        test_loss = np.mean([self.__session.run(test_loss_op) for x in range(10)])

        self.__log('Test loss: {0}'.format(test_loss))

        return train_loss <= self.__pretrain_convergence_thresh_upper, test_loss <= self.__pretrain_convergence_thresh_upper

    def __train_decoder(self, train_op, loss_op):
        samples_per_sec = 0.

        # Needed for batch norm
        update_ops = tf.compat.v1.get_collection(tf.compat.v1.GraphKeys.UPDATE_OPS)
        train_op = tf.group([train_op, update_ops])

        t = trange(self.__decoder_iterations)

        for i in t:
            if i % self.__report_rate == 0 and i > 0:
                if self.__tb_file is not None:
                    _, batch_loss, summary = self.__session.run([train_op, loss_op, self.__decoder_summaries])
                    self.__tb_writer.add_summary(summary, i)
                else:
                    _, batch_loss = self.__session.run([train_op, loss_op])

                t.set_description(
                    'DECODER - Batch {}: Loss {:.3f}, samples/sec: {:.2f}'.format(i, batch_loss, samples_per_sec))
                t.refresh()
            else:
                start_time = time.time()
                self.__session.run([train_op])
                elapsed = time.time() - start_time
                samples_per_sec = (self.__batch_size / elapsed) * self.__num_gpus

    def __test_decoder(self, decoder_ops, test_image_ops):
        self.__make_directory(os.path.join(self.results_path, 'decoder'))

        test_results = self.__session.run(test_image_ops + decoder_ops)
        test_images = test_results[:self.__num_timepoints]
        decoder_images = test_results[self.__num_timepoints:]

        for i, (test_image, decoder_output) in enumerate(list(zip(test_images, decoder_images))):
            for j in range(self.__batch_size):
                real = np.squeeze(test_image[j, :, :, :])
                self.__save_as_image(real, os.path.join(self.results_path, 'decoder', 'decoder-real-sample{0}-timestep{1}.png'.format(j, i)))

                generated = np.squeeze(decoder_output[j, :, :, :])
                self.__save_as_image(generated, os.path.join(self.results_path, 'decoder', 'decoder-generated-sample{0}-timestep{1}.png'.format(j, i)))

    def __get_weights_as_image(self, kernel, normalize=True):
        """Filter visualization, adapted with permission from https://gist.github.com/kukuruza/03731dc494603ceab0c5"""
        with self.__graph.as_default():
            pad = 1
            grid_X = 4
            grid_Y = (kernel.get_shape().as_list()[-1] / 4)
            num_channels = kernel.get_shape().as_list()[2]

            # pad X and Y
            x1 = tf.pad(tensor=kernel, paddings=tf.constant([[pad, 0], [pad, 0], [0, 0], [0, 0]]))

            # X and Y dimensions, w.r.t. padding
            Y = kernel.get_shape()[0] + pad
            X = kernel.get_shape()[1] + pad

            # pack into image with proper dimensions for tf.image_summary
            x2 = tf.transpose(a=x1, perm=(3, 0, 1, 2))
            x3 = tf.reshape(x2, tf.stack([grid_X, Y * grid_Y, X, num_channels]))
            x4 = tf.transpose(a=x3, perm=(0, 2, 1, 3))
            x5 = tf.reshape(x4, tf.stack([1, X * grid_X, Y * grid_Y, num_channels]))
            x6 = tf.transpose(a=x5, perm=(2, 1, 3, 0))
            x7 = tf.transpose(a=x6, perm=(3, 0, 1, 2))

            if normalize:
                # scale to [0, 1]
                x_min = tf.reduce_min(input_tensor=x7)
                x_max = tf.reduce_max(input_tensor=x7)
                x8 = (x7 - x_min) / (x_max - x_min)

        return x8
