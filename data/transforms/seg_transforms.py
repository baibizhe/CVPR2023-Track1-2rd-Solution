# Copyright (c) 2020 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import random
import math
import omegaconf

import cv2
import numpy as np
from PIL import Image

try:
    from collections.abc import Sequence
except Exception:
    from collections import Sequence

    
from paddleseg.transforms import functional
from paddleseg.utils import logger
import albumentations as A

class Compose:
    """
    Do transformation on input data with corresponding pre-processing and augmentation operations.
    The shape of input data to all operations is [height, width, channels].

    Args:
        transforms (list): A list contains data pre-processing or augmentation. Empty list means only reading images, no transformation.
        to_rgb (bool, optional): If converting image to RGB color space. Default: True.
        img_channels (int, optional): The image channels used to check the loaded image. Default: 3.

    Raises:
        TypeError: When 'transforms' is not a list.
        ValueError: when the length of 'transforms' is less than 1.
    """

    def __init__(self, transforms, to_rgb=True, img_channels=3):
        print("trans:", transforms, type(transforms))
        # if not isinstance(transforms, list):
        #     raise TypeError('The transforms must be a list!')
        self.transforms = transforms
        self.to_rgb = to_rgb
        self.img_channels = img_channels
        self.read_flag = cv2.IMREAD_GRAYSCALE if img_channels == 1 else cv2.IMREAD_COLOR
    
    def prepare_data(self, data):
        if 'image' not in data.keys():
                raise ValueError("`data` must include `img` key.")
        if isinstance(data['image'], str):
            data['image'] = cv2.imread(data['image'],
                                    self.read_flag).astype('float32')
        if data['image'] is None:
            raise ValueError('Can\'t read The image file {}!'.format(data[
                'image']))
        if not isinstance(data['image'], np.ndarray):
            raise TypeError("Image type is not numpy.")

        img_channels = 1 if data['image'].ndim == 2 else data['image'].shape[2]
        if img_channels != self.img_channels:
            raise ValueError(
                'The img_channels ({}) is not equal to the channel of loaded image ({})'.
                format(self.img_channels, img_channels))
        if self.to_rgb and img_channels == 3:
            data['image'] = cv2.cvtColor(data['image'], cv2.COLOR_BGR2RGB)

        if 'label' in data.keys() and isinstance(data['label'], str):
            data['label'] = np.asarray(Image.open(data['label']))

        # the `trans_info` will save the process of image shape, and will be used in evaluation and prediction.
        if 'trans_info' not in data.keys():
            data['trans_info'] = []
        return data
    
    def __call__(self, data):
        """
        Args:
            data: A dict to deal with. It may include keys: 'image', 'label', 'trans_info' and 'gt_fields'.
                'trans_info' reserve the image shape informating. And the 'gt_fields' save the key need to transforms
                together with 'image'

        Returns: A dict after process。
        """
        # 判断是否需要mosaic
        if not isinstance(data, Sequence):
            data = self.prepare_data(data)
        else: #mosaic
            for i in range(len(data)):
                data[i] = self.prepare_data(data[i])            
 
        for op in self.transforms:
            data = op(data)

        if data['image'].ndim == 2:
            data['image'] = data['image'][..., np.newaxis]
        data['image'] = np.transpose(data['image'], (2, 0, 1))
        return data


class RandomHorizontalFlip:
    """
    Flip an image horizontally with a certain probability.

    Args:
        prob (float, optional): A probability of horizontally flipping. Default: 0.5.
    """

    def __init__(self, prob=0.5):
        self.prob = prob

    def __call__(self, data):
        if random.random() < self.prob:
            data['image'] = functional.horizontal_flip(data['image'])
            for key in data.get('gt_fields', []):
                data[key] = functional.horizontal_flip(data[key])
        return data


class RandomVerticalFlip:
    """
    Flip an image vertically with a certain probability.
    Args:
        prob (float, optional): A probability of vertical flipping. Default: 0.1.
    """

    def __init__(self, prob=0.1):
        self.prob = prob

    def __call__(self, data):
        if random.random() < self.prob:
            data['image'] = functional.vertical_flip(data['image'])
            for key in data.get('gt_fields', []):
                data[key] = functional.vertical_flip(data[key])
        return data


class Resize:
    """
    Resize an image.

    Args:
        target_size (list|tuple, optional): The target size (w, h) of image. Default: (512, 512).
        keep_ratio (bool, optional): Whether to keep the same ratio for width and height in resizing.
            Default: False.
        size_divisor (int, optional): If size_divisor is not None, make the width and height be the times
            of size_divisor. Default: None.
        interp (str, optional): The interpolation mode of resize is consistent with opencv.
            ['NEAREST', 'LINEAR', 'CUBIC', 'AREA', 'LANCZOS4', 'RANDOM']. Note that when it is
            'RANDOM', a random interpolation mode would be specified. Default: "LINEAR".

    Raises:
        TypeError: When 'target_size' type is neither list nor tuple.
        ValueError: When "interp" is out of pre-defined methods ('NEAREST', 'LINEAR', 'CUBIC',
        'AREA', 'LANCZOS4', 'RANDOM').
    """

    # The interpolation mode
    interp_dict = {
        'NEAREST': cv2.INTER_NEAREST,
        'LINEAR': cv2.INTER_LINEAR,
        'CUBIC': cv2.INTER_CUBIC,
        'AREA': cv2.INTER_AREA,
        'LANCZOS4': cv2.INTER_LANCZOS4
    }

    def __init__(self,
                 target_size=(512, 512),
                 keep_ratio=False,
                 size_divisor=None,
                 interp='LINEAR'):
        if isinstance(target_size, list) or isinstance(target_size, tuple):
            if len(target_size) != 2:
                raise ValueError(
                    '`target_size` should include 2 elements, but it is {}'.
                    format(target_size))
        else:
            raise TypeError(
                "Type of `target_size` is invalid. It should be list or tuple, but it is {}"
                .format(type(target_size)))
        if not (interp == "RANDOM" or interp in self.interp_dict):
            raise ValueError("`interp` should be one of {}".format(
                self.interp_dict.keys()))
        if size_divisor is not None:
            assert isinstance(size_divisor,
                              int), "size_divisor should be None or int"

        self.target_size = target_size
        self.keep_ratio = keep_ratio
        self.size_divisor = size_divisor
        self.interp = interp

    def __call__(self, data):
        data['trans_info'].append(('resize', data['image'].shape[0:2]))
        if self.interp == "RANDOM":
            interp = random.choice(list(self.interp_dict.keys()))
        else:
            interp = self.interp

        target_size = self.target_size
        if self.keep_ratio:
            h, w = data['image'].shape[0:2]
            target_size, _ = functional.rescale_size((w, h), self.target_size)
        if self.size_divisor:
            target_size = [
                math.ceil(i / self.size_divisor) * self.size_divisor
                for i in target_size
            ]

        data['image'] = functional.resize(data['image'], target_size,
                                        self.interp_dict[interp])
        for key in data.get('gt_fields', []):
            data[key] = functional.resize(data[key], target_size,
                                          cv2.INTER_NEAREST)

        return data


class ResizeByLong:
    """
    Resize the long side of an image to given size, and then scale the other side proportionally.

    Args:
        long_size (int): The target size of long side.
    """

    def __init__(self, long_size):
        self.long_size = long_size

    def __call__(self, data):
        data['trans_info'].append(('resize', data['image'].shape[0:2]))
        data['image'] = functional.resize_long(data['image'], self.long_size)
        for key in data.get('gt_fields', []):
            data[key] = functional.resize_long(data[key], self.long_size,
                                               cv2.INTER_NEAREST)

        return data


class ResizeByShort:
    """
    Resize the short side of an image to given size, and then scale the other side proportionally.

    Args:
        short_size (int): The target size of short side.
    """

    def __init__(self, short_size):
        self.short_size = short_size

    def __call__(self, data):
        data['trans_info'].append(('resize', data['image'].shape[0:2]))
        data['image'] = functional.resize_short(data['image'], self.short_size)
        for key in data.get('gt_fields', []):
            data[key] = functional.resize_short(data[key], self.short_size,
                                                cv2.INTER_NEAREST)

        return data


class LimitLong:
    """
    Limit the long edge of image.

    If the long edge is larger than max_long, resize the long edge
    to max_long, while scale the short edge proportionally.

    If the long edge is smaller than min_long, resize the long edge
    to min_long, while scale the short edge proportionally.

    Args:
        max_long (int, optional): If the long edge of image is larger than max_long,
            it will be resize to max_long. Default: None.
        min_long (int, optional): If the long edge of image is smaller than min_long,
            it will be resize to min_long. Default: None.
    """

    def __init__(self, max_long=None, min_long=None):
        if max_long is not None:
            if not isinstance(max_long, int):
                raise TypeError(
                    "Type of `max_long` is invalid. It should be int, but it is {}"
                    .format(type(max_long)))
        if min_long is not None:
            if not isinstance(min_long, int):
                raise TypeError(
                    "Type of `min_long` is invalid. It should be int, but it is {}"
                    .format(type(min_long)))
        if (max_long is not None) and (min_long is not None):
            if min_long > max_long:
                raise ValueError(
                    '`max_long should not smaller than min_long, but they are {} and {}'
                    .format(max_long, min_long))
        self.max_long = max_long
        self.min_long = min_long

    def __call__(self, data):
        data['trans_info'].append(('resize', data['image'].shape[0:2]))

        h, w = data['image'].shape[0], data['image'].shape[1]
        long_edge = max(h, w)
        target = long_edge
        if (self.max_long is not None) and (long_edge > self.max_long):
            target = self.max_long
        elif (self.min_long is not None) and (long_edge < self.min_long):
            target = self.min_long

        if target != long_edge:
            data['image'] = functional.resize_long(data['image'], target)
            for key in data.get('gt_fields', []):
                data[key] = functional.resize_long(data[key], target,
                                                   cv2.INTER_NEAREST)

        return data



class ResizeRangeScaling:
    """
    Resize the long side of an image into a range, and then scale the other side proportionally.

    Args:
        min_value (int, optional): The minimum value of long side after resize. Default: 400.
        max_value (int, optional): The maximum value of long side after resize. Default: 600.
    """

    def __init__(self, min_value=400, max_value=600):
        if min_value > max_value:
            raise ValueError('min_value must be less than max_value, '
                             'but they are {} and {}.'.format(min_value,
                                                              max_value))
        self.min_value = min_value
        self.max_value = max_value

    def __call__(self, data):

        if self.min_value == self.max_value:
            random_size = self.max_value
        else:
            random_size = int(
                np.random.uniform(self.min_value, self.max_value) + 0.5)
        data['image'] = functional.resize_long(data['image'], random_size,
                                             cv2.INTER_LINEAR)
        for key in data.get('gt_fields', []):
            data[key] = functional.resize_long(data[key], random_size,
                                               cv2.INTER_NEAREST)

        return data


class ResizeStepScaling:
    """
    Scale an image proportionally within a range.

    Args:
        min_scale_factor (float, optional): The minimum scale. Default: 0.75.
        max_scale_factor (float, optional): The maximum scale. Default: 1.25.
        scale_step_size (float, optional): The scale interval. Default: 0.25.

    Raises:
        ValueError: When min_scale_factor is smaller than max_scale_factor.
    """

    def __init__(self,
                 min_scale_factor=0.75,
                 max_scale_factor=1.25,
                 scale_step_size=0.25):
        if min_scale_factor > max_scale_factor:
            raise ValueError(
                'min_scale_factor must be less than max_scale_factor, '
                'but they are {} and {}.'.format(min_scale_factor,
                                                 max_scale_factor))
        self.min_scale_factor = min_scale_factor
        self.max_scale_factor = max_scale_factor
        self.scale_step_size = scale_step_size

    def __call__(self, data):

        if self.min_scale_factor == self.max_scale_factor:
            scale_factor = self.min_scale_factor

        elif self.scale_step_size == 0:
            scale_factor = np.random.uniform(self.min_scale_factor,
                                             self.max_scale_factor)

        else:
            num_steps = int((self.max_scale_factor - self.min_scale_factor) /
                            self.scale_step_size + 1)
            scale_factors = np.linspace(self.min_scale_factor,
                                        self.max_scale_factor,
                                        num_steps).tolist()
            np.random.shuffle(scale_factors)
            scale_factor = scale_factors[0]
        w = int(round(scale_factor * data['image'].shape[1]))
        h = int(round(scale_factor * data['image'].shape[0]))

        data['image'] = functional.resize(data['image'], (w, h), cv2.INTER_LINEAR)  #随机缩放
        for key in data.get('gt_fields', []):
            data[key] = functional.resize(data[key], (w, h), cv2.INTER_NEAREST)

        return data


class Normalize:
    """
    Normalize an image.

    Args:
        mean (list, optional): The mean value of a data set. Default: [0.5,].
        std (list, optional): The standard deviation of a data set. Default: [0.5,].

    Raises:
        ValueError: When mean/std is not list or any value in std is 0.
    """

    def __init__(self, mean=(0.5, ), std=(0.5, )):
        if not (isinstance(mean, (list, tuple)) and isinstance(std, (list, tuple))) \
            and (len(mean) not in [1, 3]) and (len(std) not in [1, 3]):
            raise ValueError(
                "{}: input type is invalid. It should be list or tuple with the lenght of 1 or 3".
                format(self))
        self.mean = np.array(mean)
        self.std = np.array(std)

        from functools import reduce
        if reduce(lambda x, y: x * y, self.std) == 0:
            raise ValueError('{}: std is invalid!'.format(self))

    def __call__(self, data):
        data['image'] = functional.normalize(data['image'], self.mean, self.std)
        return data


class Padding:
    """
    Add bottom-right padding to a raw image or annotation image.

    Args:
        target_size (list|tuple): The target size after padding.
        im_padding_value (float, optional): The padding value of raw image.
            Default: 127.5.
        label_padding_value (int, optional): The padding value of annotation image. Default: 255.

    Raises:
        TypeError: When target_size is neither list nor tuple.
        ValueError: When the length of target_size is not 2.
    """

    def __init__(self,
                 target_size,
                 im_padding_value=127.5,
                 label_padding_value=255):
        if isinstance(target_size, list) or isinstance(target_size, tuple):
            if len(target_size) != 2:
                raise ValueError(
                    '`target_size` should include 2 elements, but it is {}'.
                    format(target_size))
        else:
            raise TypeError(
                "Type of target_size is invalid. It should be list or tuple, now is {}"
                .format(type(target_size)))
        self.target_size = target_size
        self.im_padding_value = im_padding_value
        self.label_padding_value = label_padding_value

    def __call__(self, data):
        data['trans_info'].append(('padding', data['image'].shape[0:2]))
        im_height, im_width = data['image'].shape[0], data['image'].shape[1]
        if isinstance(self.target_size, int):
            target_height = self.target_size
            target_width = self.target_size
        else:
            target_height = self.target_size[1]
            target_width = self.target_size[0]
        pad_height = target_height - im_height
        pad_width = target_width - im_width
        if pad_height < 0 or pad_width < 0:
            raise ValueError(
                'The size of image should be less than `target_size`, but the size of image ({}, {}) is larger than `target_size` ({}, {})'
                .format(im_width, im_height, target_width, target_height))
        else:
            img_channels = 1 if data['image'].ndim == 2 else data['image'].shape[2]
            data['image'] = cv2.copyMakeBorder(
                data['image'],
                0,
                pad_height,
                0,
                pad_width,
                cv2.BORDER_CONSTANT,
                value=(self.im_padding_value, ) * img_channels)
            for key in data.get('gt_fields', []):
                data[key] = cv2.copyMakeBorder(
                    data[key],
                    0,
                    pad_height,
                    0,
                    pad_width,
                    cv2.BORDER_CONSTANT,
                    value=self.label_padding_value)
        return data


class PaddingByAspectRatio:
    """

    Args:
        aspect_ratio (int|float, optional): The aspect ratio = width / height. Default: 1.
        im_padding_value (float, optional): The padding value of raw image. Default: 127.5.
        label_padding_value (int, optional): The padding value of annotation image. Default: 255.
    """

    def __init__(self,
                 aspect_ratio=1,
                 im_padding_value=127.5,
                 label_padding_value=255):
        self.aspect_ratio = aspect_ratio
        self.im_padding_value = im_padding_value
        self.label_padding_value = label_padding_value

    def __call__(self, data):

        img_height = data['image'].shape[0]
        img_width = data['image'].shape[1]
        ratio = img_width / img_height
        if ratio == self.aspect_ratio:
            return data
        elif ratio > self.aspect_ratio:
            img_height = int(img_width / self.aspect_ratio)
        else:
            img_width = int(img_height * self.aspect_ratio)
        padding = Padding(
            (img_width, img_height),
            im_padding_value=self.im_padding_value,
            label_padding_value=self.label_padding_value)
        return padding(data)


class RandomPaddingCrop:
    """
    Crop a sub-image from a raw image and annotation image randomly. If the target cropping size
    is larger than original image, then the bottom-right padding will be added.

    Args:
        crop_size (tuple, optional): The target cropping size. Default: (512, 512).
        im_padding_value (float, optional): The padding value of raw image. Default: 127.5.
        label_padding_value (int, optional): The padding value of annotation image. Default: 255.

    Raises:
        TypeError: When crop_size is neither list nor tuple.
        ValueError: When the length of crop_size is not 2.
    """

    def __init__(self,
                 crop_size=(512, 512),
                 im_padding_value=127.5,
                 label_padding_value=255):
        if isinstance(crop_size, list) or isinstance(crop_size, tuple) or isinstance(crop_size, omegaconf.listconfig.ListConfig):
            if len(crop_size) != 2:
                raise ValueError(
                    'Type of `crop_size` is list or tuple. It should include 2 elements, but it is {}'
                    .format(crop_size))
        else:
            raise TypeError(
                "The type of `crop_size` is invalid. It should be list or tuple, but it is {}"
                .format(type(crop_size)))
        self.crop_size = crop_size
        self.im_padding_value = im_padding_value
        self.label_padding_value = label_padding_value

    def __call__(self, data):

        if isinstance(self.crop_size, int):
            crop_width = self.crop_size
            crop_height = self.crop_size
        else:
            crop_width = self.crop_size[0]
            crop_height = self.crop_size[1]

        img_height = data['image'].shape[0]
        img_width = data['image'].shape[1]

        if img_height == crop_height and img_width == crop_width:
            return data
        else:
            pad_height = max(crop_height - img_height, 0)
            pad_width = max(crop_width - img_width, 0)
            img_channels = 1 if data['image'].ndim == 2 else data['image'].shape[2]
            if (pad_height > 0 or pad_width > 0):
                data['image'] = cv2.copyMakeBorder(
                    data['image'],
                    0,
                    pad_height,
                    0,
                    pad_width,
                    cv2.BORDER_CONSTANT,
                    value=(self.im_padding_value, ) * img_channels)
                for key in data.get('gt_fields', []):
                    data[key] = cv2.copyMakeBorder(
                        data[key],
                        0,
                        pad_height,
                        0,
                        pad_width,
                        cv2.BORDER_CONSTANT,
                        value=self.label_padding_value)
                img_height = data['image'].shape[0]
                img_width = data['image'].shape[1]

            if crop_height > 0 and crop_width > 0:
                h_off = np.random.randint(img_height - crop_height + 1)
                w_off = np.random.randint(img_width - crop_width + 1)

                if data['image'].ndim == 2:
                    data['image'] = data['image'][h_off:(crop_height + h_off),
                                              w_off:(w_off + crop_width)]
                else:
                    data['image'] = data['image'][h_off:(crop_height + h_off),
                                              w_off:(w_off + crop_width), :]
                for key in data.get('gt_fields', []):
                    data[key] = data[key][h_off:(crop_height + h_off), w_off:(
                        w_off + crop_width)]
        return data


class RandomCenterCrop:
    """
    Crops the given the input data at the center.
    Args:
        retain_ratio (tuple or list, optional): The length of the input list or tuple must be 2. Default: (0.5, 0.5).
        the first value is used for width and the second is for height.
        In addition, the minimum size of the cropped image is [width * retain_ratio[0], height * retain_ratio[1]].
    Raises:
        TypeError: When retain_ratio is neither list nor tuple. Default: None.
        ValueError: When the value of retain_ratio is not in [0-1].
    """

    def __init__(self, retain_ratio=(0.5, 0.5)):
        if isinstance(retain_ratio, list) or isinstance(retain_ratio, tuple):
            if len(retain_ratio) != 2:
                raise ValueError(
                    'When type of `retain_ratio` is list or tuple, it shoule include 2 elements, but it is {}'
                    .format(retain_ratio))
            if retain_ratio[0] > 1 or retain_ratio[1] > 1 or retain_ratio[
                    0] < 0 or retain_ratio[1] < 0:
                raise ValueError(
                    'Value of `retain_ratio` should be in [0, 1], but it is {}'.
                    format(retain_ratio))
        else:
            raise TypeError(
                "The type of `retain_ratio` is invalid. It should be list or tuple, but it is {}"
                .format(type(retain_ratio)))
        self.retain_ratio = retain_ratio

    def __call__(self, data):
        retain_width = self.retain_ratio[0]
        retain_height = self.retain_ratio[1]

        img_height = data['image'].shape[0]
        img_width = data['image'].shape[1]

        if retain_width == 1. and retain_height == 1.:
            return data
        else:
            randw = np.random.randint(img_width * (1 - retain_width))
            randh = np.random.randint(img_height * (1 - retain_height))
            offsetw = 0 if randw == 0 else np.random.randint(randw)
            offseth = 0 if randh == 0 else np.random.randint(randh)
            p0, p1, p2, p3 = offseth, img_height + offseth - randh, offsetw, img_width + offsetw - randw
            if data['image'].ndim == 2:
                data['image'] = data['image'][p0:p1, p2:p3]
            else:
                data['image'] = data['image'][p0:p1, p2:p3, :]
            for key in data.get('gt_fields', []):
                data[key] = data[key][p0:p1, p2:p3]

        return data


class ScalePadding:
    """
        Add center padding to a raw image or annotation image,then scale the
        image to target size.

        Args:
            target_size (list|tuple, optional): The target size of image. Default: (512, 512).
            im_padding_value (float, optional): The padding value of raw image. Default: 127.5
            label_padding_value (int, optional): The padding value of annotation image. Default: 255.

        Raises:
            TypeError: When target_size is neither list nor tuple.
            ValueError: When the length of target_size is not 2.
    """

    def __init__(self,
                 target_size=(512, 512),
                 im_padding_value=127.5,
                 label_padding_value=255):
        if isinstance(target_size, list) or isinstance(target_size, tuple):
            if len(target_size) != 2:
                raise ValueError(
                    '`target_size` should include 2 elements, but it is {}'.
                    format(target_size))
        else:
            raise TypeError(
                "Type of `target_size` is invalid. It should be list or tuple, but it is {}"
                .format(type(target_size)))

        self.target_size = target_size
        self.im_padding_value = im_padding_value
        self.label_padding_value = label_padding_value

    def __call__(self, data):
        height = data['image'].shape[0]
        width = data['image'].shape[1]

        img_channels = 1 if data['image'].ndim == 2 else data['image'].shape[2]
        if data['image'].ndim == 2:
            new_im = np.zeros((max(height, width), max(height, width)
                               )) + self.im_padding_value
        else:
            new_im = np.zeros((max(height, width), max(height, width),
                               img_channels)) + self.im_padding_value
        if 'label' in data['gt_fields']:
            new_label = np.zeros((max(height, width), max(height, width)
                                  )) + self.label_padding_value

        if height > width:
            padding = int((height - width) / 2)
            if data['image'].ndim == 2:
                new_im[:, padding:padding + width] = data['image']
            else:
                new_im[:, padding:padding + width, :] = data['image']
            if 'label' in data['gt_fields']:
                new_label[:, padding:padding + width] = data['label']
        else:
            padding = int((width - height) / 2)
            new_im[padding:padding + height, :] = data['image']
            if 'label' in data['gt_fields']:
                new_label[padding:padding + height, :] = data['label']

        data['image'] = np.uint8(new_im)
        data['image'] = functional.resize(
            data['image'], self.target_size, interp=cv2.INTER_CUBIC)
        if 'label' in data['gt_fields']:
            data['label'] = np.uint8(new_label)
            data['label'] = functional.resize(
                data['label'], self.target_size, interp=cv2.INTER_CUBIC)
        return data


class RandomNoise:
    """
    Superimposing noise on an image with a certain probability.

    Args:
        prob (float, optional): A probability of blurring an image. Default: 0.5.
        max_sigma(float, optional): The maximum value of standard deviation of the distribution.
            Default: 10.0.
    """

    def __init__(self, prob=0.5, max_sigma=10.0):
        self.prob = prob
        self.max_sigma = max_sigma

    def __call__(self, data):
        if random.random() < self.prob:
            mu = 0
            sigma = random.random() * self.max_sigma
            data['image'] = np.array(data['image'], dtype=np.float32)
            data['image'] += np.random.normal(mu, sigma, data['image'].shape)
            data['image'][data['image'] > 255] = 255
            data['image'][data['image'] < 0] = 0

        return data


class RandomBlur:
    """
    Blurring an image by a Gaussian function with a certain probability.

    Args:
        prob (float, optional): A probability of blurring an image. Default: 0.1.
        blur_type(str, optional): A type of blurring an image,
            gaussian stands for cv2.GaussianBlur,
            median stands for cv2.medianBlur,
            blur stands for cv2.blur,
            random represents randomly selected from above.
            Default: gaussian.
    """

    def __init__(self, prob=0.1, blur_type="gaussian"):
        self.prob = prob
        self.blur_type = blur_type

    def __call__(self, data):

        if self.prob <= 0:
            n = 0
        elif self.prob >= 1:
            n = 1
        else:
            n = int(1.0 / self.prob)
        if n > 0:
            if np.random.randint(0, n) == 0:
                radius = np.random.randint(3, 10)
                if radius % 2 != 1:
                    radius = radius + 1
                if radius > 9:
                    radius = 9
                data['image'] = np.array(data['image'], dtype='uint8')
                if self.blur_type == "gaussian":
                    data['image'] = cv2.GaussianBlur(data['image'],
                                                   (radius, radius), 0, 0)
                elif self.blur_type == "median":
                    data['image'] = cv2.medianBlur(data['image'], radius)
                elif self.blur_type == "blur":
                    data['image'] = cv2.blur(data['image'], (radius, radius))
                elif self.blur_type == "random":
                    select = random.random()
                    if select < 0.3:
                        data['image'] = cv2.GaussianBlur(data['image'],
                                                       (radius, radius), 0)
                    elif select < 0.6:
                        data['image'] = cv2.medianBlur(data['image'], radius)
                    else:
                        data['image'] = cv2.blur(data['image'], (radius, radius))
                else:
                    data['image'] = cv2.GaussianBlur(data['image'],
                                                   (radius, radius), 0, 0)
        data['image'] = np.array(data['image'], dtype='float32')
        return data


class RandomRotation:
    """
    Rotate an image randomly with padding.

    Args:
        max_rotation (float, optional): The maximum rotation degree. Default: 15.
        im_padding_value (float, optional): The padding value of raw image. Default: 127.5.
        label_padding_value (int, optional): The padding value of annotation image. Default: 255.
    """

    def __init__(self,
                 max_rotation=15,
                 im_padding_value=127.5,
                 label_padding_value=255):
        self.max_rotation = max_rotation
        self.im_padding_value = im_padding_value
        self.label_padding_value = label_padding_value

    def __call__(self, data):

        if self.max_rotation > 0:
            (h, w) = data['image'].shape[:2]
            img_channels = 1 if data['image'].ndim == 2 else data['image'].shape[2]
            do_rotation = np.random.uniform(-self.max_rotation,
                                            self.max_rotation)
            pc = (w // 2, h // 2)
            r = cv2.getRotationMatrix2D(pc, do_rotation, 1.0)
            cos = np.abs(r[0, 0])
            sin = np.abs(r[0, 1])

            nw = int((h * sin) + (w * cos))
            nh = int((h * cos) + (w * sin))

            (cx, cy) = pc
            r[0, 2] += (nw / 2) - cx
            r[1, 2] += (nh / 2) - cy
            dsize = (nw, nh)
            data['image'] = cv2.warpAffine(
                data['image'],
                r,
                dsize=dsize,
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(self.im_padding_value, ) * img_channels)
            for key in data.get('gt_fields', []):
                data[key] = cv2.warpAffine(
                    data[key],
                    r,
                    dsize=dsize,
                    flags=cv2.INTER_NEAREST,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=self.label_padding_value)

        return data


class RandomScaleAspect:
    """
    Crop a sub-image from an original image with a range of area ratio and aspect and
    then scale the sub-image back to the size of the original image.

    Args:
        min_scale (float, optional): The minimum area ratio of cropped image to the original image. Default: 0.5.
        aspect_ratio (float, optional): The minimum aspect ratio. Default: 0.33.
    """

    def __init__(self, min_scale=0.5, aspect_ratio=0.33):
        self.min_scale = min_scale
        self.aspect_ratio = aspect_ratio

    def __call__(self, data):

        if self.min_scale != 0 and self.aspect_ratio != 0:
            img_height = data['image'].shape[0]
            img_width = data['image'].shape[1]
            for i in range(0, 10):
                area = img_height * img_width
                target_area = area * np.random.uniform(self.min_scale, 1.0)
                aspectRatio = np.random.uniform(self.aspect_ratio,
                                                1.0 / self.aspect_ratio)

                dw = int(np.sqrt(target_area * 1.0 * aspectRatio))
                dh = int(np.sqrt(target_area * 1.0 / aspectRatio))
                if (np.random.randint(10) < 5):
                    tmp = dw
                    dw = dh
                    dh = tmp

                if (dh < img_height and dw < img_width):
                    h1 = np.random.randint(0, img_height - dh)
                    w1 = np.random.randint(0, img_width - dw)

                    if data['image'].ndim == 2:
                        data['image'] = data['image'][h1:(h1 + dh), w1:(w1 + dw)]
                    else:
                        data['image'] = data['image'][h1:(h1 + dh), w1:(w1 + dw), :]
                    data['image'] = cv2.resize(
                        data['image'], (img_width, img_height),
                        interpolation=cv2.INTER_LINEAR)
                    for key in data.get('gt_fields', []):
                        data[key] = data[key][h1:(h1 + dh), w1:(w1 + dw)]
                        data[key] = cv2.resize(
                            data[key], (img_width, img_height),
                            interpolation=cv2.INTER_NEAREST)
                    break
        return data


class RandomDistort:
    """
    Distort an image with random configurations.

    Args:
        brightness_range (float, optional): A range of brightness. Default: 0.5.
        brightness_prob (float, optional): A probability of adjusting brightness. Default: 0.5.
        contrast_range (float, optional): A range of contrast. Default: 0.5.
        contrast_prob (float, optional): A probability of adjusting contrast. Default: 0.5.
        saturation_range (float, optional): A range of saturation. Default: 0.5.
        saturation_prob (float, optional): A probability of adjusting saturation. Default: 0.5.
        hue_range (int, optional): A range of hue. Default: 18.
        hue_prob (float, optional): A probability of adjusting hue. Default: 0.5.
        sharpness_range (float, optional): A range of sharpness. Default: 0.5.
        sharpness_prob (float, optional): A probability of adjusting saturation. Default: 0.
    """

    def __init__(self,
                 brightness_range=0.5,
                 brightness_prob=0.5,
                 contrast_range=0.5,
                 contrast_prob=0.5,
                 saturation_range=0.5,
                 saturation_prob=0.5,
                 hue_range=18,
                 hue_prob=0.5,
                 sharpness_range=0.5,
                 sharpness_prob=0):
        self.brightness_range = brightness_range
        self.brightness_prob = brightness_prob
        self.contrast_range = contrast_range
        self.contrast_prob = contrast_prob
        self.saturation_range = saturation_range
        self.saturation_prob = saturation_prob
        self.hue_range = hue_range
        self.hue_prob = hue_prob
        self.sharpness_range = sharpness_range
        self.sharpness_prob = sharpness_prob

    def __call__(self, data):

        brightness_lower = 1 - self.brightness_range
        brightness_upper = 1 + self.brightness_range
        contrast_lower = 1 - self.contrast_range
        contrast_upper = 1 + self.contrast_range
        saturation_lower = 1 - self.saturation_range
        saturation_upper = 1 + self.saturation_range
        hue_lower = -self.hue_range
        hue_upper = self.hue_range
        sharpness_lower = 1 - self.sharpness_range
        sharpness_upper = 1 + self.sharpness_range
        ops = [
            functional.brightness, functional.contrast, functional.saturation,
            functional.sharpness
        ]
        if data['image'].ndim > 2:
            ops.append(functional.hue)
        random.shuffle(ops)
        params_dict = {
            'brightness': {
                'brightness_lower': brightness_lower,
                'brightness_upper': brightness_upper
            },
            'contrast': {
                'contrast_lower': contrast_lower,
                'contrast_upper': contrast_upper
            },
            'saturation': {
                'saturation_lower': saturation_lower,
                'saturation_upper': saturation_upper
            },
            'hue': {
                'hue_lower': hue_lower,
                'hue_upper': hue_upper
            },
            'sharpness': {
                'sharpness_lower': sharpness_lower,
                'sharpness_upper': sharpness_upper,
            }
        }
        prob_dict = {
            'brightness': self.brightness_prob,
            'contrast': self.contrast_prob,
            'saturation': self.saturation_prob,
            'hue': self.hue_prob,
            'sharpness': self.sharpness_prob
        }
        data['image'] = data['image'].astype('uint8')
        data['image'] = Image.fromarray(data['image'])
        for id in range(len(ops)):
            params = params_dict[ops[id].__name__]
            prob = prob_dict[ops[id].__name__]
            params['im'] = data['image']
            if np.random.uniform(0, 1) < prob:
                data['image'] = ops[id](**params)
        data['image'] = np.asarray(data['image']).astype('float32')
        return data


class RandomAffine:
    """
    Affine transform an image with random configurations.

    Args:
        size (tuple, optional): The target size after affine transformation. Default: (224, 224).
        translation_offset (float, optional): The maximum translation offset. Default: 0.
        max_rotation (float, optional): The maximum rotation degree. Default: 15.
        min_scale_factor (float, optional): The minimum scale. Default: 0.75.
        max_scale_factor (float, optional): The maximum scale. Default: 1.25.
        im_padding_value (float, optional): The padding value of raw image. Default: 128.
        label_padding_value (int, optional): The padding value of annotation image. Default: (255, 255, 255).
    """

    def __init__(self,
                 size=(224, 224),
                 translation_offset=0,
                 max_rotation=15,
                 min_scale_factor=0.75,
                 max_scale_factor=1.25,
                 im_padding_value=128,
                 label_padding_value=255):
        self.size = size
        self.translation_offset = translation_offset
        self.max_rotation = max_rotation
        self.min_scale_factor = min_scale_factor
        self.max_scale_factor = max_scale_factor
        self.im_padding_value = im_padding_value
        self.label_padding_value = label_padding_value

    def __call__(self, data):

        w, h = self.size
        bbox = [0, 0, data['image'].shape[1] - 1, data['image'].shape[0] - 1]
        x_offset = (random.random() - 0.5) * 2 * self.translation_offset
        y_offset = (random.random() - 0.5) * 2 * self.translation_offset
        dx = (w - (bbox[2] + bbox[0])) / 2.0
        dy = (h - (bbox[3] + bbox[1])) / 2.0

        matrix_trans = np.array([[1.0, 0, dx], [0, 1.0, dy], [0, 0, 1.0]])

        angle = random.random() * 2 * self.max_rotation - self.max_rotation
        scale = random.random() * (self.max_scale_factor - self.min_scale_factor
                                   ) + self.min_scale_factor
        scale *= np.mean(
            [float(w) / (bbox[2] - bbox[0]), float(h) / (bbox[3] - bbox[1])])
        alpha = scale * math.cos(angle / 180.0 * math.pi)
        beta = scale * math.sin(angle / 180.0 * math.pi)

        centerx = w / 2.0 + x_offset
        centery = h / 2.0 + y_offset
        matrix = np.array(
            [[alpha, beta, (1 - alpha) * centerx - beta * centery],
             [-beta, alpha, beta * centerx + (1 - alpha) * centery],
             [0, 0, 1.0]])

        matrix = matrix.dot(matrix_trans)[0:2, :]
        img_channels = 1 if data['image'].ndim == 2 else data['image'].shape[2]
        data['image'] = cv2.warpAffine(
            np.uint8(data['image']),
            matrix,
            tuple(self.size),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(self.im_padding_value, ) * img_channels)
        for key in data.get('gt_fields', []):
            data[key] = cv2.warpAffine(
                np.uint8(data[key]),
                matrix,
                tuple(self.size),
                flags=cv2.INTER_NEAREST,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=self.label_padding_value)
        return data


class GenerateInstanceTargets:
    """
    Generate instance targets from ground-truth labels.

    Args:
        num_classes (int): The number of classes.
        ignore_index (int, optional): Specifies a target value that is ignored. Default: 255.
    """

    def __init__(self, num_classes, ignore_index=255):
        self.num_classes = num_classes
        self.ignore_index = ignore_index

    def __call__(self, data):
        if 'label' in data:
            sem_seg_gt = data['label']
            instances = {"image_shape": data['image'].shape[1:]}
            classes = np.unique(sem_seg_gt) 
            classes = classes[classes != self.ignore_index]   #有10个类别  删除255
 
            # To make data compatible with dataloader
            classes_cpt = np.array([
                self.ignore_index
                for _ in range(self.num_classes - len(classes))
            ])
            classes_cpt = np.append(classes, classes_cpt)
            instances["gt_classes"] = np.asarray(classes_cpt).astype('int64')

            masks = []
            for cid in classes:
                masks.append(sem_seg_gt == cid)  # [C, H, W] 

            shape = [self.num_classes - len(masks)] + list(data['label'].shape)  #(无效class数量, shape)
            masks_cpt = np.zeros(shape, dtype='int64')

            if len(masks) == 0:
                # Some images do not have annotation and will all be ignored
                instances['gt_masks'] = np.zeros(
                    (self.num_classes, sem_seg_gt.shape[-2],
                     sem_seg_gt.shape[-1]),
                    dtype='int64')

            else:
                instances['gt_masks'] = np.concatenate(
                    [
                        np.stack([
                            np.ascontiguousarray(x).astype('float32')
                            for x in masks
                        ]), masks_cpt
                    ],
                    axis=0)
            instances['image_path'] = data['image_path']
            data['instances'] = instances

        return data


##
#随机选择一个方式
class One_of_aug:
    def __init__(self, method, p, only_img = False):
        self.transform = A.OneOf(method, p = p)
        self.only_img = only_img
    def __call__(self, data):
        if self.only_img:
            # cv2.imwrite('org.png',data['image'])
            augs = self.transform(image=np.uint8(data['image']))
            data['image'] = augs['image'].astype('float32')
            # cv2.imwrite('after.png',data['image'])
        else:
            # org = np.hstack((data['image'], np.stack((data['label'],data['label'],data['label']),-1)))
            # cv2.imwrite('org.png',org)
            augs = self.transform(image=np.uint8(data['image']), mask = data['label'])  #同时变换两个
            data['image'], data['label']= augs['image'].astype('float32'), augs['mask']
            # after = np.hstack((data['image'], np.stack((data['label'],data['label'],data['label']),-1)))
            # cv2.imwrite('after.png',after)
        return data

#随机天气
class RandomWeather:
    def __init__(self,):
        super(RandomWeather, self).__init__()
        self.transform = A.Compose([    
                                A.OneOf([  #噪声类       
                                        A.RandomRain(drop_length=20, drop_width=1, drop_color=(200, 200, 200),   #drop_width雨的粗细
                                                blur_value=3, brightness_coefficient=0.9, rain_type=None, always_apply=False, p=0.4), #增加雨
                                        A.RandomFog(fog_coef_lower=0.1, fog_coef_upper=0.25, alpha_coef=0.25, always_apply=False, p=0.6)  #随机增加雾
                                ]),
                            ],p = 1.0)
    def __call__(self, data):
        augs = self.transform(image=np.uint8(data['image']))
        data['image'] = augs['image'].astype('float32')
        return data


class RandomSelectAug:
    def __init__(self, transforms1, transforms2, p):
        super(RandomSelectAug, self).__init__()
        self.transforms1 = transforms1
        self.transforms2 = transforms2
        self.p = p

    def __call__(self, data):
        if random.random() < self.p:
            return self.transforms1(data)
        else:
            return self.transforms2(data)




class Mosaic:
    def __init__(self, prob=1.0, input_dim=[640, 640]):
        self.prob = prob
        self.input_dim = input_dim
        print('=================>分割马赛克')
    
    def get_mosaic_coords(self, mosaic_idx, xc, yc, w, h, input_h, input_w):
        # (x1, y1, x2, y2) means coords in large image,
        # small_coords means coords in small image in mosaic aug.
        if mosaic_idx == 0:
            # top left
            x1, y1, x2, y2 = max(xc - w, 0), max(yc - h, 0), xc, yc
            small_coords = w - (x2 - x1), h - (y2 - y1), w, h
        elif mosaic_idx == 1:
            # top right
            x1, y1, x2, y2 = xc, max(yc - h, 0), min(xc + w, input_w * 2), yc
            small_coords = 0, h - (y2 - y1), min(w, x2 - x1), h
        elif mosaic_idx == 2:
            # bottom left
            x1, y1, x2, y2 = max(xc - w, 0), yc, xc, min(input_h * 2, yc + h)
            small_coords = w - (x2 - x1), 0, w, min(y2 - y1, h)
        elif mosaic_idx == 3:
            # bottom right
            x1, y1, x2, y2 = xc, yc, min(xc + w, input_w * 2), min(input_h * 2,
                                                                   yc + h)
            small_coords = 0, 0, min(w, x2 - x1), min(y2 - y1, h)

        return (x1, y1, x2, y2), small_coords
        
    def __call__(self, data):
        if not isinstance(data, Sequence):  
            return data
        assert len(data) == 4, "Mosaic needs 4 samples"
        
        # current_iter = data[0]['curr_iter']
        # if current_iter < self.start_decrease_iter:
        #     prob = self.prob
        # elif current_iter > (self.start_decrease_iter + self.decrease_iter):
        #     return data[0]
        # else:
        #     prob = max(0,self.prob - self.prob * (current_iter-self.start_decrease_iter) / self.decrease_iter)  #逐渐衰减 
        if np.random.uniform(0., 1.) > self.prob:
            return data[0]
        
        # input_h, input_w = self.input_dim
        input_w, input_h = self.input_dim

        yc = int(random.uniform(0.75 * input_h, 1.25 * input_h))
        xc = int(random.uniform(0.75 * input_w, 1.25 * input_w))
        mosaic_img = np.full((input_h * 2, input_w * 2, 3), 114, dtype=np.uint8)
        mosaic_label = np.full((input_h * 2, input_w * 2), 255, dtype=np.uint8)  # 背景是255
        
        for mosaic_idx, sp in enumerate(data):
            img = sp['image']
            label = sp['label']
            h0, w0 = img.shape[:2]
            scale = min(1. * input_h / h0, 1. * input_w / w0)
            img = cv2.resize(
                img, (int(w0 * scale), int(h0 * scale)),
                interpolation=cv2.INTER_LINEAR)
            label = cv2.resize(label, (int(w0 * scale), int(h0 * scale)),
                interpolation=cv2.INTER_NEAREST)
            (h, w, c) = img.shape[:3]

            # suffix l means large image, while s means small image in mosaic aug.
            (l_x1, l_y1, l_x2, l_y2), (
                s_x1, s_y1, s_x2, s_y2) = self.get_mosaic_coords(
                    mosaic_idx, xc, yc, w, h, input_h, input_w)

            mosaic_img[l_y1:l_y2, l_x1:l_x2] = img[s_y1:s_y2, s_x1:s_x2]
            mosaic_label[l_y1:l_y2, l_x1:l_x2] = label[s_y1:s_y2, s_x1:s_x2]
        
        data0 = data[0]
        data0['image'] = mosaic_img.astype(np.uint8)
        data0['label'] = mosaic_label.astype(np.uint8)

        # cv2.imwrite('1111.png',data0['image'] )

        return data0
