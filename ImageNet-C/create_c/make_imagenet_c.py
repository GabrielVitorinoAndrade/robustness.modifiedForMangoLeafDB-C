# -*- coding: utf-8 -*-

import os
from PIL import Image
import os.path
import time
import torch
import torchvision.transforms as trn
import torch.utils.data as data
import numpy as np

from PIL import Image
import skimage as sk
from skimage.filters import gaussian
from io import BytesIO
from wand.image import Image as WandImage
from wand.api import library as wandlibrary
import wand.color as WandColor
import ctypes
from PIL import Image as PILImage
import cv2
from scipy.ndimage import zoom as scizoom
from scipy.ndimage.interpolation import map_coordinates
import warnings

warnings.simplefilter("ignore", UserWarning)

# /////////////// Data Loader ///////////////

IMG_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.ppm', '.bmp', '.pgm']

def is_image_file(filename):
    """Checks if a file is an image.
    Args:
        filename (string): path to a file
    Returns:
        bool: True if the filename ends with a known image extension
    """
    filename_lower = filename.lower()
    return any(filename_lower.endswith(ext) for ext in IMG_EXTENSIONS)

def find_classes(dir):
    classes = [d for d in os.listdir(dir) if os.path.isdir(os.path.join(dir, d))]
    classes.sort()
    class_to_idx = {classes[i]: i for i in range(len(classes))}
    return classes, class_to_idx

def make_dataset(dir, class_to_idx):
    images = []
    dir = os.path.expanduser(dir)
    for target in sorted(os.listdir(dir)):
        d = os.path.join(dir, target)
        if not os.path.isdir(d):
            continue

        for root, _, fnames in sorted(os.walk(d)):
            for fname in sorted(fnames):
                if is_image_file(fname):
                    path = os.path.join(root, fname)
                    item = (path, class_to_idx[target])
                    images.append(item)

    return images

def pil_loader(path):
    # open path as file to avoid ResourceWarning
    with open(path, 'rb') as f:
        img = Image.open(f)
        return img.convert('RGB')

def default_loader(path):
    return pil_loader(path)

class DistortImageFolder(data.Dataset):
    def __init__(self, root, method, severity, transform=None, target_transform=None,
                 loader=default_loader, output_dir='./distorted_images'):
        classes, class_to_idx = find_classes(root)
        imgs = make_dataset(root, class_to_idx)
        if len(imgs) == 0:
            raise RuntimeError("Found 0 images in subfolders of: " + root + "\n"
                              "Supported image extensions are: " + ",".join(IMG_EXTENSIONS))

        self.root = root
        self.method = method
        self.severity = severity
        self.imgs = imgs
        self.classes = classes
        self.class_to_idx = class_to_idx
        self.idx_to_class = {v: k for k, v in class_to_idx.items()}
        self.transform = transform
        self.target_transform = target_transform
        self.loader = loader
        self.output_dir = output_dir


    def __getitem__(self, index):
        path, target = self.imgs[index]
        img = self.loader(path)
        
        # Resize to 224x224 if it's not already that size
        if img.size != (224, 224):
            img = img.resize((224, 224), Image.LANCZOS)
            
        # Apply transformation if any
        if self.transform is not None:
            img = self.transform(img)
            img = self.method(img, self.severity)

        if self.target_transform is not None:
            target = self.target_transform(target)

        # Create output directory if it doesn't exist
        save_dir = os.path.join(self.output_dir, self.method.__name__, str(self.severity), self.idx_to_class[target])
        if not os.path.exists(save_dir):
            try:
                os.makedirs(save_dir)
            except FileExistsError:
                pass  # Diretório já existe, o que é aceitável

        # Extract filename without directory path
        filename = os.path.basename(path)
        save_path = os.path.join(save_dir, filename)

        # Save the distorted image
        Image.fromarray(np.uint8(img)).save(save_path, quality=95, optimize=True)

        return 0  # we do not care about returning the data

    def __len__(self):
        return len(self.imgs)

# /////////////// Distortion Helpers ///////////////

def auc(errs):  # area under the alteration error curve
    area = 0
    for i in range(1, len(errs)):
        area += (errs[i] + errs[i - 1]) / 2
    area /= len(errs) - 1
    return area

def disk(radius, alias_blur=0.1, dtype=np.float32):
    if radius <= 8:
        L = np.arange(-8, 8 + 1)
        ksize = (3, 3)
    else:
        L = np.arange(-radius, radius + 1)
        ksize = (5, 5)
    X, Y = np.meshgrid(L, L)
    aliased_disk = np.array((X ** 2 + Y ** 2) <= radius ** 2, dtype=dtype)
    aliased_disk /= np.sum(aliased_disk)

    # supersample disk to antialias
    return cv2.GaussianBlur(aliased_disk, ksize=ksize, sigmaX=alias_blur)

# Tell Python about the C method
wandlibrary.MagickMotionBlurImage.argtypes = (ctypes.c_void_p,  # wand
                                              ctypes.c_double,  # radius
                                              ctypes.c_double,  # sigma
                                              ctypes.c_double)  # angle

# Extend wand.image.Image class to include method signature
class MotionImage(WandImage):
    def motion_blur(self, radius=0.0, sigma=0.0, angle=0.0):
        wandlibrary.MagickMotionBlurImage(self.wand, radius, sigma, angle)

# Generate a plasma fractal for fog effect
def plasma_fractal(mapsize=256, wibbledecay=3):
    """
    Generate a heightmap using diamond-square algorithm.
    Return square 2d array, side length 'mapsize', of floats in range 0-255.
    'mapsize' must be a power of two.
    """
    assert (mapsize & (mapsize - 1) == 0)
    maparray = np.empty((mapsize, mapsize), dtype=np.float_)
    maparray[0, 0] = 0
    stepsize = mapsize
    wibble = 100

    def wibbledmean(array):
        return array / 4 + wibble * np.random.uniform(-wibble, wibble, array.shape)

    def fillsquares():
        """For each square of points stepsize apart,
           calculate middle value as mean of points + wibble"""
        cornerref = maparray[0:mapsize:stepsize, 0:mapsize:stepsize]
        squareaccum = cornerref + np.roll(cornerref, shift=-1, axis=0)
        squareaccum += np.roll(squareaccum, shift=-1, axis=1)
        maparray[stepsize // 2:mapsize:stepsize,
        stepsize // 2:mapsize:stepsize] = wibbledmean(squareaccum)

    def filldiamonds():
        """For each diamond of points stepsize apart,
           calculate middle value as mean of points + wibble"""
        mapsize = maparray.shape[0]
        drgrid = maparray[stepsize // 2:mapsize:stepsize, stepsize // 2:mapsize:stepsize]
        ulgrid = maparray[0:mapsize:stepsize, 0:mapsize:stepsize]
        ldrsum = drgrid + np.roll(drgrid, 1, axis=0)
        lulsum = ulgrid + np.roll(ulgrid, -1, axis=1)
        ltsum = ldrsum + lulsum
        maparray[0:mapsize:stepsize, stepsize // 2:mapsize:stepsize] = wibbledmean(ltsum)
        tdrsum = drgrid + np.roll(drgrid, 1, axis=1)
        tulsum = ulgrid + np.roll(ulgrid, -1, axis=0)
        ttsum = tdrsum + tulsum
        maparray[stepsize // 2:mapsize:stepsize, 0:mapsize:stepsize] = wibbledmean(ttsum)

    while stepsize >= 2:
        fillsquares()
        filldiamonds()
        stepsize //= 2
        wibble /= wibbledecay

    maparray -= maparray.min()
    return maparray / maparray.max()

def clipped_zoom(img, zoom_factor):
    h = img.shape[0]
    # ceil crop height(= crop width)
    ch = int(np.ceil(h / zoom_factor))

    top = (h - ch) // 2
    img = scizoom(img[top:top + ch, top:top + ch], (zoom_factor, zoom_factor, 1), order=1)
    # trim off any extra pixels
    trim_top = (img.shape[0] - h) // 2

    return img[trim_top:trim_top + h, trim_top:trim_top + h]

# /////////////// Distortions ///////////////

def gaussian_noise(x, severity=1):
    c = [.08, .12, 0.18, 0.26, 0.38][severity - 1]

    x = np.array(x) / 255.
    return np.clip(x + np.random.normal(size=x.shape, scale=c), 0, 1) * 255

def shot_noise(x, severity=1):
    c = [60, 25, 12, 5, 3][severity - 1]

    x = np.array(x) / 255.
    return np.clip(np.random.poisson(x * c) / c, 0, 1) * 255

def impulse_noise(x, severity=1):
    c = [.03, .06, .09, 0.17, 0.27][severity - 1]

    x = sk.util.random_noise(np.array(x) / 255., mode='s&p', amount=c)
    return np.clip(x, 0, 1) * 255

def speckle_noise(x, severity=1):
    c = [.15, .2, 0.35, 0.45, 0.6][severity - 1]

    x = np.array(x) / 255.
    return np.clip(x + x * np.random.normal(size=x.shape, scale=c), 0, 1) * 255

def gaussian_blur(x, severity=1):
    c = [1, 2, 3, 4, 6][severity - 1]

    # x = gaussian(np.array(x) / 255., sigma=c, multichannel=True)
    x = gaussian(np.array(x) / 255., sigma=c, channel_axis=-1)  # Alterado aqui
    return np.clip(x, 0, 1) * 255

def glass_blur(x, severity=1):
    # sigma, max_delta, iterations
    c = [(0.7, 1, 2), (0.9, 2, 1), (1, 2, 3), (1.1, 3, 2), (1.5, 4, 2)][severity - 1]

    # x = np.uint8(gaussian(np.array(x) / 255., sigma=c[0], multichannel=True) * 255)

    x = np.uint8(gaussian(np.array(x) / 255., sigma=c[0], channel_axis=-1) * 255)  # Primeira correção

    # locally shuffle pixels
    for i in range(c[2]):
        for h in range(224 - c[1], c[1], -1):
            for w in range(224 - c[1], c[1], -1):
                dx, dy = np.random.randint(-c[1], c[1], size=(2,))
                h_prime, w_prime = h + dy, w + dx
                # swap
                x[h, w], x[h_prime, w_prime] = x[h_prime, w_prime], x[h, w]

    # return np.clip(gaussian(x / 255., sigma=c[0], multichannel=True), 0, 1) * 255
    return np.clip(gaussian(x / 255., sigma=c[0], channel_axis=-1), 0, 1) * 255  # Segunda correção

def defocus_blur(x, severity=1):
    c = [(3, 0.1), (4, 0.5), (6, 0.5), (8, 0.5), (10, 0.5)][severity - 1]

    x = np.array(x) / 255.
    kernel = disk(radius=c[0], alias_blur=c[1])

    channels = []
    for d in range(3):
        channels.append(cv2.filter2D(x[:, :, d], -1, kernel))
    channels = np.array(channels).transpose((1, 2, 0))  # 3x224x224 -> 224x224x3

    return np.clip(channels, 0, 1) * 255

def motion_blur(x, severity=1):
    c = [(10, 3), (15, 5), (15, 8), (15, 12), (20, 15)][severity - 1]

    output = BytesIO()
    x.save(output, format='PNG')
    x = MotionImage(blob=output.getvalue())

    x.motion_blur(radius=c[0], sigma=c[1], angle=np.random.uniform(-45, 45))

    x = cv2.imdecode(np.fromstring(x.make_blob(), np.uint8),
                     cv2.IMREAD_UNCHANGED)

    if x.shape != (224, 224):
        return np.clip(x[..., [2, 1, 0]], 0, 255)  # BGR to RGB
    else:  # greyscale to RGB
        return np.clip(np.array([x, x, x]).transpose((1, 2, 0)), 0, 255)

def zoom_blur(x, severity=1):
    c = [np.arange(1, 1.11, 0.01),
         np.arange(1, 1.16, 0.01),
         np.arange(1, 1.21, 0.02),
         np.arange(1, 1.26, 0.02),
         np.arange(1, 1.31, 0.03)][severity - 1]

    x = (np.array(x) / 255.).astype(np.float32)
    out = np.zeros_like(x)
    for zoom_factor in c:
        out += clipped_zoom(x, zoom_factor)

    x = (x + out) / (len(c) + 1)
    return np.clip(x, 0, 1) * 255

def fog(x, severity=1):
    c = [(1.5, 2), (2, 2), (2.5, 1.7), (2.5, 1.5), (3, 1.4)][severity - 1]

    x = np.array(x) / 255.
    max_val = x.max()
    x += c[0] * plasma_fractal(wibbledecay=c[1])[:224, :224][..., np.newaxis]
    return np.clip(x * max_val / (max_val + c[0]), 0, 1) * 255

def frost(x, severity=1):
    c = [(1, 0.4),
         (0.8, 0.6),
         (0.7, 0.7),
         (0.65, 0.7),
         (0.6, 0.75)][severity - 1]
    
    # Create frost texture
    noise_size = 224
    noise = np.random.normal(size=(noise_size, noise_size), loc=0, scale=1)
    # Smooth the noise and scale it to [0, 1]
    frost = gaussian(noise, sigma=2)
    frost = (frost - frost.min()) / (frost.max() - frost.min())
    frost = frost[:224, :224][..., np.newaxis]
    
    x = np.array(x) / 255.
    return np.clip(c[0] * x + c[1] * frost, 0, 1) * 255

def snow(x, severity=1):
    c = [(0.1, 0.3, 3, 0.5, 10, 4, 0.8),
         (0.2, 0.3, 2, 0.5, 12, 4, 0.7),
         (0.55, 0.3, 4, 0.9, 12, 8, 0.7),
         (0.55, 0.3, 4.5, 0.85, 12, 8, 0.65),
         (0.55, 0.3, 2.5, 0.85, 12, 12, 0.55)][severity - 1]

    x = np.array(x, dtype=np.float32) / 255.
    snow_layer = np.random.normal(size=x.shape[:2], loc=c[0], scale=c[1])
    
    snow_layer = clipped_zoom(snow_layer[..., np.newaxis], c[2])
    snow_layer[snow_layer < c[3]] = 0
    
    # Convert snow layer to binary mask
    snow_layer = snow_layer.squeeze()
    snow_mask = snow_layer > 0
    snow_mask = snow_mask[..., np.newaxis]
    
    # Apply snow effect
    x = c[6] * x + (1 - c[6]) * np.maximum(x, cv2.cvtColor(x, cv2.COLOR_RGB2GRAY).reshape(224, 224, 1) * 1.5 + 0.5)
    whiten = np.ones_like(x) * 0.8  # snow is bright
    
    # Apply snow to the image
    x = np.where(snow_mask, whiten, x)
    
    return np.clip(x, 0, 1) * 255

def contrast(x, severity=1):
    c = [0.4, .3, .2, .1, .05][severity - 1]

    x = np.array(x) / 255.
    means = np.mean(x, axis=(0, 1), keepdims=True)
    return np.clip((x - means) * c + means, 0, 1) * 255

def brightness(x, severity=1):
    c = [.1, .2, .3, .4, .5][severity - 1]

    x = np.array(x) / 255.
    x = sk.color.rgb2hsv(x)
    x[:, :, 2] = np.clip(x[:, :, 2] + c, 0, 1)
    x = sk.color.hsv2rgb(x)

    return np.clip(x, 0, 1) * 255

def saturate(x, severity=1):
    c = [(0.3, 0), (0.1, 0), (2, 0), (5, 0.1), (20, 0.2)][severity - 1]

    x = np.array(x) / 255.
    x = sk.color.rgb2hsv(x)
    x[:, :, 1] = np.clip(x[:, :, 1] * c[0] + c[1], 0, 1)
    x = sk.color.hsv2rgb(x)

    return np.clip(x, 0, 1) * 255

def jpeg_compression(x, severity=1):
    c = [25, 18, 15, 10, 7][severity - 1]

    output = BytesIO()
    x.save(output, 'JPEG', quality=c)
    x = PILImage.open(output)

    return np.array(x)

def pixelate(x, severity=1):
    c = [0.6, 0.5, 0.4, 0.3, 0.25][severity - 1]

    x = x.resize((int(224 * c), int(224 * c)), PILImage.BOX)
    x = x.resize((224, 224), PILImage.BOX)

    return np.array(x)

def elastic_transform(image, severity=1):
    c = [(224 * 2, 224 * 0.7, 224 * 0.1),   # Fixed 244 to 224
         (224 * 2, 224 * 0.08, 224 * 0.2),
         (224 * 0.05, 224 * 0.01, 224 * 0.02),
         (224 * 0.07, 224 * 0.01, 224 * 0.02),
         (224 * 0.12, 224 * 0.01, 224 * 0.02)][severity - 1]

    image = np.array(image, dtype=np.float32) / 255.
    shape = image.shape
    shape_size = shape[:2]

    # random affine
    center_square = np.float32(shape_size) // 2
    square_size = min(shape_size) // 3
    pts1 = np.float32([center_square + square_size,
                       [center_square[0] + square_size, center_square[1] - square_size],
                       center_square - square_size])
    pts2 = pts1 + np.random.uniform(-c[2], c[2], size=pts1.shape).astype(np.float32)
    M = cv2.getAffineTransform(pts1, pts2)
    image = cv2.warpAffine(image, M, shape_size[::-1], borderMode=cv2.BORDER_REFLECT_101)

    dx = (gaussian(np.random.uniform(-1, 1, size=shape[:2]),
                   c[1], mode='reflect', truncate=3) * c[0]).astype(np.float32)
    dy = (gaussian(np.random.uniform(-1, 1, size=shape[:2]),
                   c[1], mode='reflect', truncate=3) * c[0]).astype(np.float32)
    dx, dy = dx[..., np.newaxis], dy[..., np.newaxis]

    x, y, z = np.meshgrid(np.arange(shape[1]), np.arange(shape[0]), np.arange(shape[2]))
    indices = np.reshape(y + dy, (-1, 1)), np.reshape(x + dx, (-1, 1)), np.reshape(z, (-1, 1))
    return np.clip(map_coordinates(image, indices, order=1, mode='reflect').reshape(shape), 0, 1) * 255

def spatter(x, severity=1):
    c = [(0.62,0.1,0.7,0.7,0.5,0),
         (0.65,0.1,0.8,0.7,0.5,0),
         (0.65,0.3,1,0.69,0.5,0),
         (0.65,0.1,0.7,0.69,0.6,1),
         (0.65,0.1,0.5,0.68,0.6,1)][severity - 1]
    x = np.array(x, dtype=np.float32) / 255.

    liquid_layer = np.random.normal(size=x.shape[:2], loc=c[0], scale=c[1])

    liquid_layer = gaussian(liquid_layer, sigma=c[2])
    liquid_layer[liquid_layer < c[3]] = 0
    if c[5] == 0:
        liquid_layer = (liquid_layer * 255).astype(np.uint8)
        dist = 255 - cv2.Canny(liquid_layer, 50, 150)
        dist = cv2.distanceTransform(dist, cv2.DIST_L2, 5)
        _, dist = cv2.threshold(dist, 20, 20, cv2.THRESH_TRUNC)
        dist = cv2.blur(dist, (3, 3)).astype(np.uint8)
        dist = cv2.equalizeHist(dist)
        #     ker = np.array([[-1,-2,-3],[-2,0,0],[-3,0,1]], dtype=np.float32)
        #     ker -= np.mean(ker)
        ker = np.array([[-2, -1, 0], [-1, 1, 1], [0, 1, 2]])
        dist = cv2.filter2D(dist, cv2.CV_8U, ker)
        dist = cv2.blur(dist, (3, 3)).astype(np.float32)

        m = cv2.cvtColor(liquid_layer * dist, cv2.COLOR_GRAY2BGRA)
        m /= np.max(m, axis=(0, 1))
        m *= c[4]

        # water is pale turqouise
        color = np.concatenate((175 / 255. * np.ones_like(m[..., :1]),
                                238 / 255. * np.ones_like(m[..., :1]),
                                238 / 255. * np.ones_like(m[..., :1])), axis=2)

        color = cv2.cvtColor(color, cv2.COLOR_BGR2BGRA)
        x = cv2.cvtColor(x, cv2.COLOR_BGR2BGRA)

        return cv2.cvtColor(np.clip(x + m * color, 0, 1), cv2.COLOR_BGRA2BGR) * 255
    else:
        m = np.where(liquid_layer > c[3], 1, 0)
        m = gaussian(m.astype(np.float32), sigma=c[4])
        m[m < 0.8] = 0
        #         m = np.abs(m) ** (1/c[4])

        # mud brown
        color = np.concatenate((63 / 255. * np.ones_like(x[..., :1]),
                                42 / 255. * np.ones_like(x[..., :1]),
                                20 / 255. * np.ones_like(x[..., :1])), axis=2)

        color *= m[..., np.newaxis]
        x *= (1 - m[..., np.newaxis])

        return np.clip(x + color, 0, 1) * 255

# /////////////// Main Function ///////////////

def apply_distortions(dataset_path, output_base_dir='./distorted_dataset'):
    """
    Apply various distortion methods to images in the dataset.
    
    Args:
        dataset_path: Path to the dataset, expected to contain class folders
        output_base_dir: Base directory to save distorted images
    """
    # Create base output directory
    if not os.path.exists(output_base_dir):
        os.makedirs(output_base_dir)
    
    # Define distortion methods
    distortions = {
        'Gaussian_Noise': gaussian_noise,
        'Shot_Noise': shot_noise,
        'Impulse_Noise': impulse_noise,
        'Defocus_Blur': defocus_blur,
        'Glass_Blur': glass_blur,
        'Motion_Blur': motion_blur,
        'Zoom_Blur': zoom_blur,
        'Snow': snow,
        'Frost': frost,
        'Fog': fog,
        'Brightness': brightness,
        'Contrast': contrast,
        'Elastic': elastic_transform,
        'Pixelate': pixelate,
        'JPEG': jpeg_compression,
        'Speckle_Noise': speckle_noise,
        'Gaussian_Blur': gaussian_blur,
        'Saturate': saturate,
        'Spatter': spatter
    }
    
    # Loop through each distortion method
    for method_name, method_func in distortions.items():
        print(f"Applying {method_name}...")
        
        # Apply each severity level
        for severity in range(1, 6):
            print(f"  Severity level: {severity}")
            
        
            # Create dataset with the distortion
            distorted_dataset = DistortImageFolder(
                root=dataset_path,
                method=method_func, 
                severity=severity,
                transform=trn.Compose([trn.Resize(224), trn.CenterCrop(224)]),
                output_dir=output_base_dir
            )
            
            # Process all images with a DataLoader
            data_loader = torch.utils.data.DataLoader(
                distorted_dataset, batch_size=16, shuffle=False, num_workers=4
            )
            
            # Run the loader to process all images
            total_batches = len(data_loader)
            # Na função apply_distortions:
            # Loop através de todas as imagens
            for i, _ in enumerate(data_loader):
                if (i + 1) % 10 == 0 or (i + 1) == total_batches:
                    print(f"    Processed {i+1}/{total_batches} batches")

if __name__ == "__main__":
    # Path to your dataset containing 8 class folders
    # Modify this to match your dataset path
    # DATASET_PATH = "./your_dataset_path"


    #In our case, the dataset we want to corrupt is MangoLeafDB. Which is made up of 8 classes, where each class has 500 images.
    #And it is located in "C:/MangoLeafDB"
    DATASET_PATH = "C:/MangoLeafDB"
    
    #After executing the code we will have the MangoLeafDB-C dataset which is the MangoLeafDB with the structure described in readme.md
    OUTPUT_DIR = "C:/MangoLeafDB-C"
    
    # Apply all distortions
    apply_distortions(DATASET_PATH, OUTPUT_DIR)
