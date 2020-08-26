import lsplab as lab
import os
import datetime
import sys
# Paths and other info to change for your experiment.

# The location of the images
image_directory = sys.argv[1]
# We're loading a dataset from a Lemnatec system so let's point to the metadata file.
snapshot_info_path = sys.argv[2]

# These are where to save intermediate files we are going to generate.
index_output_path = '.chickpea.bgwas'
records_output_path = 'chickpea/records'
records_filename = 'Setaria-RIL'
records_full_path = os.path.join(records_output_path, records_filename)

if not os.path.exists(records_output_path):
    os.makedirs(records_output_path)

# Height and width of images in the dataset. If they're huge, resize them first. Between 256x256 and 512x512 is good.
image_height = 332
image_width = 257

# Number of cpu threads to use.
num_threads = 20

# How many gpus to use for training.
num_gpus = 1

# This is usually a good batch size. Larger batch sizes may cause you to run out of GPU memory.
batch_size = 16

# What you want to name this run. The results will be saved in a folder called Setaria-results.
name = 'Setaria'

# Create the .bgwas index file from the snapshot file (if necessary). See below for options.
num_timepoints = lab.biotools.snapshot2bgwas(snapshot_info_path,
                                             index_output_path,
                                             timestamp_format="%Y-%m-%d_%H-%M-%S",
                                             prefix="RGB SV1",
                                             barcode_regex='^([A-Za-z]+)+(\d+)([A-Z][A-Z])\d+$',
                                             treatments={
                                                 "AA": 0,
                                                 "BB": 1
                                             })

# Create the tfrecords from the dataset using the .bgwas index, and images folder (if necessary)
lab.biotools.bgwas2tfrecords(index_output_path, image_directory, records_output_path, records_filename)

# Make a new experiment. debug=True means that we will print out info to the console.
model = lab.lsp(debug=True, batch_size=batch_size)

# Load the records we just built.
model.load_records(records_output_path, image_height, image_width, num_timepoints)

model.set_use_memory_cache(True)

# Start the model. See below for options.
model.start(pretraining_epochs=10, report_rate=100, name=name, decoder_vis=True, num_gpus=num_gpus, num_threads=num_threads)