import torch
import torch.optim as optim
from torch.optim import lr_scheduler
import torch.nn as nn
import numpy as np
import pandas as pd
import rawpy
from tqdm import tqdm as pbar
import copy
from livelossplot import PlotLosses
import matplotlib.pyplot as plt
import seaborn
seaborn.set()
import scipy

inp_image = 'dataset/Sony/short/a.ARW'

def post_process(raw):
    """
    Input: object returned from rawpy.imgread()
    Output: numpy array in shape (2848, 4256, 3)
    """
    max_output = 65535.0
    im = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=16)
    im = np.float32(im / max_output)
    return im

  
def pack_raw(raw):
    """
    Input: object returned from rawpy.imread()
    Output: numpy array in shape (1424, 2128, 4)
    """
    
    im = raw.raw_image_visible.astype(np.float32) # shape of (2848, 4256)
    im = np.maximum(im - 512, 0) / (16383 - 512) #subtract the black level
    im = np.expand_dims(im, axis=2) # shape of (2848, 4256, 1)

    img_shape = im.shape # (H, W, 1)
    H = img_shape[0]
    W = img_shape[1]
    
    # Pack into 4 channels
    red = im[0:H:2,0:W:2,:]
    green_1 = im[0:H:2,1:W:2,:]
    blue = im[1:H:2,1:W:2,:]
    green_2 = im[1:H:2,0:W:2,:]
    
    # Final shape: (1424, 2128, 4)
    out = np.concatenate((red, green_1, blue, green_2), axis=2)
    return out
def numpy_to_torch(image):
    """
    Input: numpy array (H x W x C)
    Output: torch tensory (C x H x W)
    """
    image = image.transpose((2, 0, 1))
    torch_tensor = torch.from_numpy(image)
    return torch_tensor
  
  

def display_custom_image(model, image_path, amp_ratio, render=False):
    model.eval()
        
    orig_image = post_process(rawpy.imread(image_path))
    
    fig=plt.figure(figsize=(20, 10))
    fig.add_subplot(1, 2, 1)
    plt.imshow(orig_image, vmin=0, vmax=1)
    plt.title('Original image')
    plt.axis('off')
    plt.grid(b=None)
    
    image = pack_raw(rawpy.imread(image_path)) * amp_ratio
    image = numpy_to_torch(np.clip(image, a_min=0.0, a_max=1.0)).unsqueeze(0)
    image = image.to(device)
    with torch.no_grad():
        y_hat = model(image)
        y_hat = torch.clamp(y_hat, min=0.0, max=1.0)
    image = y_hat.squeeze().cpu().numpy().transpose((1, 2, 0))
        
    fig.add_subplot(1, 2, 2)
    plt.imshow(image, vmin=0, vmax=1)
    plt.title('Denoised by model')
    plt.axis('off')
    plt.grid(b=None)
    
    if render:
        scipy.misc.toimage(image * 255, high=255, low=0, cmin=0, cmax=255).save('custom_images/processed.png')

    plt.show()



class DoubleConv(nn.Module):
    #  Conv -> BN -> LReLU -> Conv -> BN -> LReLU
    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.f = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1),
            nn.BatchNorm2d(out_ch),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Conv2d(out_ch, out_ch, 3, padding=1),
            nn.BatchNorm2d(out_ch),
            nn.LeakyReLU(0.2, inplace=True),)
    def forward(self, x):
        x = self.f(x)
        return x


class Down(nn.Module):
    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.f = nn.Sequential(
            nn.MaxPool2d(2),
            DoubleConv(in_ch, out_ch),)
    def forward(self, x):
        x = self.f(x)
        return x


class Up(nn.Module):
    # upsample and concat
    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.upsample = nn.ConvTranspose2d(in_ch, in_ch//2, 2, stride=2)
        self.conv = DoubleConv(in_ch, out_ch)
    def forward(self, x1, x2):
        x1 = self.upsample(x1)
        x = torch.cat([x2, x1], dim=1)
        x = self.conv(x)
        return x


class OutConv(nn.Module):
    def __init__(self, in_ch, out_ch):
        super(OutConv, self).__init__()
        self.f = nn.Conv2d(in_ch, out_ch, 1)
    def forward(self, x):
        x = self.f(x)
        return x

class Unet(nn.Module):
    def __init__(self):
        super().__init__()
        self.inc = DoubleConv(4, 32)
        self.d1 = Down(32, 64)
        self.d2 = Down(64, 128)
        self.d3 = Down(128, 256)
        self.d4 = Down(256, 512)

        self.u1 = Up(512, 256)
        self.u2 = Up(256, 128)
        self.u3 = Up(128, 64)
        self.u4 = Up(64, 32)
        self.outc = OutConv(32, 12)
        self.pixel_shuffle = nn.PixelShuffle(2)

    def forward(self, x):
        x1 = self.inc(x)
        x2 = self.d1(x1)
        x3 = self.d2(x2)
        x4 = self.d3(x3)
        x5 = self.d4(x4)
        x = self.u1(x5, x4)
        x = self.u2(x, x3)
        x = self.u3(x, x2)
        x = self.u4(x, x1)
        x = self.outc(x)
        x = self.pixel_shuffle(x)
        return x



device = torch.device('cuda:0' if torch.cuda.is_available() else'cpu')

my_model = Unet()
my_model.load_state_dict(torch.load('trained_model/best_model.pt',map_location=device))
my_model = my_model.to(device)

display_custom_image(my_model, inp_image, 150)
