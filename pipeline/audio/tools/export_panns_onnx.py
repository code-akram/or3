# /// script
# requires-python = "==3.12.*"
# dependencies = ["torch==2.8.0", "torchlibrosa==0.1.0", "onnx>=1.17", "numpy<2.4"]
# [[tool.uv.index]]
# name = "pytorch-cpu"
# url = "https://download.pytorch.org/whl/cpu"
# explicit = true
# [tool.uv.sources]
# torch = { index = "pytorch-cpu" }
# ///
"""Export the PANNs Cnn14_16k AudioSet tagger to ONNX for the human-presence check (audiopipe.tagger).

    uv run pipeline/audio/tools/export_panns_onnx.py <model dir>

<model dir> holds `Cnn14_16k_mAP=0.438.pth` (Zenodo record 3987831, CC BY 4.0, md5
362fc5ff18f1d6ad2f6d464b45893f2c). Writes `cnn14_16k.onnx` next to it: input `waveform`
(batch, samples) float32 at 16 kHz mono, output `clipwise` (batch, 527) sigmoid scores in
AudioSet class order (metadata/class_labels_indices.csv of the same repo).

The network definition below is the Cnn14 of qiuqiangkong/audioset_tagging_cnn (pytorch/models.py,
MIT licence, Kong et al. 2020), reduced to inference (no SpecAugment, no mixup, no dropout).
torch only runs here, in a throwaway uv environment; the pipeline itself needs onnxruntime only.
Weights and the ONNX file stay in private/ (never committed).
"""

import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from torchlibrosa.stft import LogmelFilterBank, Spectrogram


class ConvBlock(nn.Module):
    def __init__(self, cin: int, cout: int) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(cin, cout, kernel_size=(3, 3), stride=(1, 1), padding=(1, 1), bias=False)
        self.conv2 = nn.Conv2d(cout, cout, kernel_size=(3, 3), stride=(1, 1), padding=(1, 1), bias=False)
        self.bn1 = nn.BatchNorm2d(cout)
        self.bn2 = nn.BatchNorm2d(cout)

    def forward(self, x, pool_size=(2, 2)):
        x = F.relu(self.bn1(self.conv1(x)))
        x = F.relu(self.bn2(self.conv2(x)))
        return F.avg_pool2d(x, kernel_size=pool_size)


class Cnn14(nn.Module):
    def __init__(self, sample_rate=16000, window_size=512, hop_size=160, mel_bins=64, fmin=50, fmax=8000, classes_num=527):
        super().__init__()
        self.spectrogram_extractor = Spectrogram(n_fft=window_size, hop_length=hop_size, win_length=window_size,
                                                 window="hann", center=True, pad_mode="reflect", freeze_parameters=True)
        self.logmel_extractor = LogmelFilterBank(sr=sample_rate, n_fft=window_size, n_mels=mel_bins, fmin=fmin, fmax=fmax,
                                                 ref=1.0, amin=1e-10, top_db=None, freeze_parameters=True)
        self.bn0 = nn.BatchNorm2d(64)
        self.conv_block1 = ConvBlock(1, 64)
        self.conv_block2 = ConvBlock(64, 128)
        self.conv_block3 = ConvBlock(128, 256)
        self.conv_block4 = ConvBlock(256, 512)
        self.conv_block5 = ConvBlock(512, 1024)
        self.conv_block6 = ConvBlock(1024, 2048)
        self.fc1 = nn.Linear(2048, 2048, bias=True)
        self.fc_audioset = nn.Linear(2048, classes_num, bias=True)

    def forward(self, waveform):
        x = self.spectrogram_extractor(waveform)   # (B, 1, T, F)
        x = self.logmel_extractor(x)               # (B, 1, T, mel)
        x = x.transpose(1, 3)
        x = self.bn0(x)
        x = x.transpose(1, 3)
        for blk in (self.conv_block1, self.conv_block2, self.conv_block3, self.conv_block4, self.conv_block5):
            x = blk(x, pool_size=(2, 2))
        x = self.conv_block6(x, pool_size=(1, 1))
        x = torch.mean(x, dim=3)
        x = torch.max(x, dim=2)[0] + torch.mean(x, dim=2)
        x = F.relu(self.fc1(x))
        return torch.sigmoid(self.fc_audioset(x))


def main() -> None:
    d = Path(sys.argv[1])
    ckpt = torch.load(d / "Cnn14_16k_mAP=0.438.pth", map_location="cpu", weights_only=False)
    model = Cnn14()
    missing, unexpected = model.load_state_dict(ckpt["model"], strict=False)
    # spec_augmenter has no parameters; anything else missing would be a real error
    assert not missing, missing
    print("ignored checkpoint keys:", unexpected)
    model.eval()
    dummy = torch.zeros(1, 32000)
    out = d / "cnn14_16k.onnx"
    torch.onnx.export(model, (dummy,), str(out), input_names=["waveform"], output_names=["clipwise"],
                      dynamic_axes={"waveform": {0: "batch", 1: "samples"}, "clipwise": {0: "batch"}},
                      opset_version=17, dynamo=False)
    # parity check against torch on a noise clip
    import numpy as np
    import onnx
    onnx.checker.check_model(str(out))
    x = torch.randn(2, 32000) * 0.05
    with torch.no_grad():
        ref = model(x).numpy()
    print("exported", out, "torch ref shape", ref.shape)
    np.save(d / "parity_input.npy", x.numpy())
    np.save(d / "parity_ref.npy", ref)


if __name__ == "__main__":
    main()
