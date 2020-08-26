import os
import sys
import re
from PIL import Image

def resize_images(path):
    dirs = os.listdir(path)
    for image_path in [os.path.join(path, f) for f in dirs if f[-4:] == '.png']:
        if os.path.isfile(image_path):
            im = Image.open(image_path)
            f, e = os.path.splitext(image_path)
            # and lower can be represented as (upper+height
            (left, upper, right, lower) = (500, 1128, 1972, 2600)
            imCrop = im.crop((left, upper, right, lower))
            imResize = imCrop.resize((368, 368), Image.ANTIALIAS)
            imResize.save(f + ' resized.png', 'PNG')


if __name__ == "__main__":
    resize_images(sys.argv[1])