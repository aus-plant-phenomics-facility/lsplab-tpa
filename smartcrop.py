import os
import sys
import re
import cv2
import numpy as np 

def resize_images(path, outpath):
    dirs = os.listdir(path)
    xmax = 2000
    ymax = 2000
    hmax = 0
    wmax = 0
    for image_path in [os.path.join(path, f) for f in dirs if f[-4:] == '.png']:
        if os.path.isfile(image_path):
            #removeds rgba component
            img = cv2.imread(image_path, cv2.IMREAD_COLOR)
            gray = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
            ret,thresh = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)
            contours,hierarchy = cv2.findContours(thresh, 1, 2)
            for c in contours:
                x,y,w,h = cv2.boundingRect(c)
                #sane bounds on the image
                if w<500 or h<500: 
                    continue
                else:
                    xmax = min(x, xmax)
                    ymax = min(y, ymax)
                    hmax = max(y+h, hmax)
                    wmax = max(x+w, wmax)
                    # print(w,wmax, h, hmax)
                    # print("big one", x,y,w,h)
                    # cv2.rectangle(result, (x, y), (x+w-1, y+h-1), (0, 0, 255), 1)
                    break;
    print("finished bounding")
    for image_path in [os.path.join(path, f) for f in dirs if f[-4:] == '.png']:
        if os.path.isfile(image_path):
            #removeds rgba component
            img = cv2.imread(image_path, cv2.IMREAD_COLOR)
            crop = img[ymax-30:hmax+30, x-30:wmax+30]
            f, e = os.path.splitext(image_path)
            path = outpath + f.split('/')[1] + ".png"

            scale_percent = 35# percent of original size
            width = int(crop.shape[1] * scale_percent / 100)
            height = int(crop.shape[0] * scale_percent / 100)
            dim = (width, height)
            
            # resize image
            resized = cv2.resize(crop, dim, interpolation = cv2.INTER_AREA)
            cv2.imwrite(path, resized)


if __name__ == "__main__":
    resize_images(sys.argv[1], sys.argv[2])