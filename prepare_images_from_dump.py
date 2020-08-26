import os
import sys
import re
from PIL import Image


def rename_files(dir_to_flatten):
    for dirpath, dirnames, filenames in os.walk(dir_to_flatten):
        for filename in [f for f in filenames if f[-4:] == '.png']:
            try:
                path = dirpath.split(os.sep)

                camera_label = path[-1]
                snapshot_directory = path[-2]
                pattern = "(.*)_([A-Z\d- ]+)_(\d\d\d\d-\d\d-\d\d_\d\d-\d\d-\d\d)_(\d+)"

                matches = re.findall(pattern, snapshot_directory)[0]

                measurement_label = matches[0]
                id_tag = matches[1]
                time_stamp = matches[2]
                blobId = matches[3]

                os.rename(os.path.join(dirpath, filename),
                          os.path.join(dir_to_flatten, "{}_{}_{}.png".format(camera_label, id_tag, time_stamp)))

            except OSError:
                print("Could not move %s " % os.path.join(dirpath, filename))


def purge_directory_if_not_match(dir, pattern):
    for f in os.listdir(dir):
        if not re.search(pattern, f):
            try:
                os.remove(os.path.join(dir, f))
            except:
                try:
                    os.rmdir(os.path.join(dir, f))
                except:
                    pass


def resize_images(path):
    dirs = os.listdir(path)
    for image_path in [os.path.join(path, f) for f in dirs if f[-4:] == '.png']:
        if os.path.isfile(image_path):
            im = Image.open(image_path)
            f, e = os.path.splitext(image_path)
            imResize = im.resize((257, 332), Image.ANTIALIAS)
            imResize.save(f + ' resized.png', 'PNG')


if __name__ == "__main__":
    dir_to_flatten = sys.argv[1]
    # rename_files(dir_to_flatten)
    purge_directory_if_not_match(dir_to_flatten, "RGB SV1")
    # resize_images(dir_to_flatten)
