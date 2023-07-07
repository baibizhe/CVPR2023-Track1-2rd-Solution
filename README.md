English | [简体中文](README_ch.md)

# CVPR-2023-Track1-2rd-solution

## Instructions

We provide a three task  AllInOne joint training method of classification, detection, and segmentation.

Demo is based on 8 A100 cards.

### Environment

Please use python3.7 and cuda11.2. 

```bash
pip install -r requirements.txt
```

setup paddleseg.
```bash
cd /PaddleSeg
pip install -r requirements.txt
pip install -v -e .
```

setup mask2former
```bash
cd /PaddleSeg/contrib/PanopticSeg/paddlepanseg/models/ops
cd ms_deform_attn
python setup.py install
```
if you are facing   error: ‘_cvtss_sh’ was not declared in this scope error: ‘_cvtsh_ss’ was not declared in this scope.
add  #include <immintrin.h> to .../site-packages/paddle/include/paddle/phi/common/float16.h
### Data Configuration

You can download the data from: https://pan.baidu.com/s/10HDywKyzu6R8q-Lxrpn3pw (J69v) ,and decompress the data into the 'datasets' folder 


### Pretrained model

We use swin trainsformer Large as our backbone, mask2former as our seg head and Dino as our det head

All the pretrained model above can be download from: https://pan.baidu.com/s/10HDywKyzu6R8q-Lxrpn3pw (J69v)


### Training


```bash
sh scripts/train.sh
```

### Inference


```bash
sh scripts/test.sh
```


### Our best model 

Can be download from: https://pan.baidu.com/s/10HDywKyzu6R8q-Lxrpn3pw (J69v)
