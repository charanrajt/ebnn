from __future__ import absolute_import
import math

import chainer
import numpy as np

from ..links import CLink
from ..links import BinaryConvolution2D
from ..links import BatchNormalization
from ..links import BST
from ..utils import binary_util as bu


class ConvBNBST(chainer.Chain, CLink):
    def __init__(self, in_channels, out_channels, ksize, stride=1, pad=0):
        super(ConvBNBST, self).__init__()
        with self.init_scope():
            self.bconv = BinaryConvolution2D(
                in_channels, out_channels, ksize, stride=stride, pad=pad)
            self.bn = BatchNormalization(out_channels)
            self.bst = BST()
        self.cname = "l_conv_bn_bst"

    def __call__(self, h, test=False):
        h = self.bst(self.bn(self.bconv(h)))
        return h

    def generate_c(self, link_idx, inp_shape):
        w, h = inp_shape[2:4]
        name = self.cname + str(link_idx)
        text = []
        m = 1
        sw, sh = self.bconv.stride
        pw, ph = self.bconv.pad
        pl_w, pl_h = 1, 1
        pl_sw, pl_sh = 1, 1
        pl_pw, pl_ph = 0, 0

        # Bconv
        l = self.bconv
        lname = name + '_' + l.name
        for p in l.params():
            pname = p.name
            if pname == 'W':
                num_f, n, kw, kh = p.data.shape
                bin_data = bu.binarize_real(
                    p.data).reshape(p.data.shape[0], -1)
                text += [bu.np_to_uint8C(bin_data, lname +
                                         '_' + pname, 'row_major', pad='1')]
            elif pname == 'b':
                text += [bu.np_to_floatC(p.data, lname +
                                         '_' + pname, 'row_major')]

        # BatchNormalization bn
        l = self.bn
        lName = l.name
        lname = name + '_' + lName
        for p in l.params():
            pname = p.name
            if pname == 'gamma':
                text += [bu.np_to_floatC(p.data, lname +
                                         '_' + pname, 'row_major')]
            elif pname == 'beta':
                text += [bu.np_to_floatC(p.data, lname +
                                         '_' + pname, 'row_major')]
        for p in l._persistent:
            pname = p
            persistent = l.__dict__[p]
            if pname == 'avg_mean':
                text += [bu.np_to_floatC(persistent,
                                         lname + '_mean', 'row_major')]
            elif pname == 'avg_var':
                text += [bu.np_to_floatC(np.sqrt(persistent,
                                                 dtype=persistent.dtype), lname + '_std', 'row_major')]
        text = "\n".join(text) + '\n'
        ftext = "void {name}(float* input, uint8_t* output){{\n"
        ftext += "  fconv_layer(input, {name}_bconv_W, output, {name}_bconv_b, {name}_bn_gamma, {name}_bn_beta, {name}_bn_mean, {name}_bn_std, {m}, {num_f}, {w}, {h}, {n}, {kw}, {kh}, {sw}, {sh}, {pw}, {ph}, {pl_w}, {pl_h}, {pl_sw}, {pl_sh}, {pl_pw}, {pl_ph});\n}}\n\n"
        ftext = ftext.format(name=name, m=m, n=n, w=w, h=h, num_f=num_f, kw=kw,
                             kh=kh, sw=sw, sh=sh, pw=pw, ph=ph, pl_w=pl_w,
                             pl_h=pl_h, pl_sw=pl_sw, pl_sh=pl_sh, pl_pw=pl_pw,
                             pl_ph=pl_ph)
        text += ftext

        return text

    def param_mem(self):
        mem = 0.
        l = self.bconv
        for p in self.bconv.params():
            if p.name == 'W':
                num_f, n, kw, kh = p.data.shape
                # Filters
                mem += num_f * n * kh * math.ceil(kw / 8.)
                #Bias + BN
                mem += 5 * num_f * 32

        return mem

    def temp_mem(self, inp_shape):
        # TODO: UPDATE
        m, n, w, h = inp_shape
        sw, sh = self.bconv.stride
        for p in self.bconv.params():
            if p.name == 'W':
                _, _, kw, kh = p.data.shape
                break

        res_w = (w - kw + 8) / 8
        res_h = h - kh + 1

        return m * n * res_w * res_h
