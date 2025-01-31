"""transforms/build.py
"""

import paddle.vision.transforms as T
import numpy as np
import random
import albumentations as A
from timm.data.random_erasing import RandomErasing
# from .random_erasing import RandomErasing
# from fastreid.data.transforms import *
from fastreid.data.transforms.autoaugment import AutoAugment
from PIL import Image
import cv2

class RandomApply(object):
    """RandomApply
    """
    def __init__(self, prob=0.5, transform_function_class=None):
        self.prob = prob
        self.transform_function = transform_function_class()
    
    def __call__(self, x):
        if random.random() > self.prob:
            return self.transform_function(x)
        else:
            return x

class RandomPatch(object):
    def __init__(self, prob=0.5, transform_function_class=None):
        self.aug =  A.Compose([        
                A.RandomGridShuffle(grid=(2,2), always_apply=False, p=prob), #网格打乱     
        ])
        print('==============>use grid shuffle')
    
    def __call__(self, x, mask =None):
        x = np.array(x)
        if mask is None:
            trans = self.aug(image = x)
            img = trans['image']
            # cv2.imwrite('gridshuffle.png',img)
            return Image.fromarray(img)
        else:
            mask = np.array(mask)
            trans = self.aug(image = x, mask = mask)
            img,mask= trans['image'], trans['mask']
            return  Image.fromarray(img),  Image.fromarray(mask)


class My_aug(object):
    """RandomApply
    """
    def __init__(self):
        self.aug = A.Compose([    
                            A.OneOf([  #改变位置的数据增强
                                    A.Rotate (limit=15, p=0.5), 
                                    A.ShiftScaleRotate(rotate_limit=15, p=0.5),
                            ], p = 0.3),
                            A.OneOf([  #模糊类
                                    A.Blur(blur_limit=[3,5], p=0.2), 
                                    A.GaussianBlur(blur_limit=[3,5], sigma_limit=[0,1], p = 0.2),
                                    A.ImageCompression(quality_lower=40, quality_upper=80, p=0.2),  
                                    A.ToGray(p=0.4),
                                    ],p = 0.3),   
                            A.OneOf([  #噪声类
                                    A.ISONoise(color_shift=(0.02,0.05), intensity=(0.1,0.3), p=0.5),  
                                    A.GaussNoise(var_limit=(10.0, 30.0), p=0.5),  
                                    ],p = 0.3),    
            ])
        print('==============>use My_aug')
    def __call__(self, x, mask =None):
        x = np.array(x)
        if mask is None:
            trans = self.aug(image = x)
            img = trans['image']
            return Image.fromarray(img)
        else:
            mask = np.array(mask)
            trans = self.aug(image = x, mask = mask)
            img,mask= trans['image'], trans['mask']
            return  Image.fromarray(img),  Image.fromarray(mask)  



class ToArray(object):
    """ToArray
    """
    def __call__(self, img):
        img = np.array(img)
        img = np.transpose(img, [2, 0, 1])
        # img = img / 255.
        return img.astype('float32')


def build_transforms_lazy(is_train=True, **kwargs):
    """
    build transforms of image data,
    only support `is_train=False`
    """
    res = []
    if is_train:
        size_train = kwargs.get('size_train', [256, 128])
        # crop
        do_crop = kwargs.get('do_crop', False)
        crop_size = kwargs.get('crop_size', [224, 224])
        crop_scale = kwargs.get('crop_scale', [0.16, 1])
        crop_ratio = kwargs.get('crop_ratio', [3. / 4., 4. / 3.])

        # augmix augmentation
        do_augmix = kwargs.get('do_augmix', False)
        augmix_prob = kwargs.get('augmix_prob', 0.0)

        # auto augmentation
        do_autoaug = kwargs.get('do_autoaug', False)
        autoaug_prob = kwargs.get('autoaug_prob', 0.0)

        # horizontal filp
        do_flip = kwargs.get('do_flip', False)
        flip_prob = kwargs.get('flip_prob', 0.5)

        # padding
        do_pad = kwargs.get('do_pad', False)
        padding_size = kwargs.get('padding_size', 10)
        padding_mode = kwargs.get('padding_mode', 'constant')

        # color jitter
        do_cj = kwargs.get('do_cj', False)
        cj_prob = kwargs.get('cj_prob', 0.5)
        cj_brightness = kwargs.get('cj_brightness', 0.15)
        cj_contrast = kwargs.get('cj_contrast', 0.15)
        cj_saturation = kwargs.get('cj_saturation', 0.1)
        cj_hue = kwargs.get('cj_hue', 0.1)

        # random affine
        do_affine = kwargs.get('do_affine', False)

        # random erasing
        do_rea = kwargs.get('do_rea', False)
        rea_prob = kwargs.get('rea_prob', 0.5)
        rea_value = list(kwargs.get('rea_value', [0.485 * 255, 0.456 * 255, 0.406 * 255]))

        # random patch
        do_rpt = kwargs.get('do_rpt', False)
        # rpt_prob = kwargs.get('rpt_prob', 0.5)

        do_myaug = kwargs.get('do_myaug', False)

        # normalize
        mean = kwargs.get('mean', [0.485 * 255, 0.456 * 255, 0.406 * 255])
        std = kwargs.get('std', [0.229 * 255, 0.224 * 255, 0.225 * 255])

        if do_autoaug:
            res.append(RandomApply(prob=autoaug_prob, transform_function_class=AutoAugment))

        if size_train[0] > 0:
            res.append(T.Resize(size_train[0] if len(size_train) == 1 else size_train, interpolation='bicubic'))

        if do_crop:
            res.append(T.RandomResizedCrop(size=crop_size[0] if len(crop_size) == 1 else crop_size,
                                           interpolation='bicubic',
                                           scale=crop_scale, ratio=crop_ratio))
        if do_pad:
            res.extend([T.Pad(padding_size, padding_mode=padding_mode),
                        T.RandomCrop(size_train[0] if len(size_train) == 1 else size_train)])
        if do_flip:
            res.append(T.RandomHorizontalFlip( prob=flip_prob))

        # if do_cj:
        #     res.append(T.RandomApply([T.ColorJitter(cj_brightness, cj_contrast, cj_saturation, cj_hue)], p=cj_prob))  
        # if do_affine:
        #     res.append(T.RandomAffine(degrees=10, translate=None, scale=[0.9, 1.1], shear=0.1, resample=False,
                                    #   fillcolor=0))
        # if do_augmix:
        #     res.append(AugMix(prob=augmix_prob)) 

        if do_myaug:
            res.append(My_aug())
        if do_rpt:
            res.append(RandomPatch())
        
        res.append(ToArray())
        res.append(T.Normalize(mean=mean, std=std))
        if do_rea:
            # RandomErasing depends on the lib timm, which requires torch.
            import torch
            res.append(lambda x: torch.Tensor(x))
            res.append(RandomErasing(probability=rea_prob, mode='pixel', max_count=2, device='cpu'))
            res.append(lambda x: np.array(x))

            # RandomErasing is implemented by paddle clas; TODO to ensure the results of the version of paddle clas are comparable with the one of timm
            # res.append(RandomErasing(EPSILON=rea_prob))

    else:
        size_test = kwargs.get('size_test', [256, 128])
        do_crop = kwargs.get('do_crop', False)
        crop_size = kwargs.get('crop_size', [224, 224])
        # normalize
        mean = kwargs.get('mean', [0.485 * 255, 0.456 * 255, 0.406 * 255])
        std = kwargs.get('std', [0.229 * 255, 0.224 * 255, 0.225 * 255])

        if size_test[0] > 0:
            res.append(T.Resize(size_test[0] if len(size_test) == 1 else size_test, interpolation='bicubic'))
        if do_crop:
            res.append(T.CenterCrop(size=crop_size[0] if len(crop_size) == 1 else crop_size))
        res.append(ToArray())
        res.append(T.Normalize(mean=mean, std=std))
    return T.Compose(res)
