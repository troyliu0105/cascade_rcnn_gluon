"""RCNN Model."""
from __future__ import absolute_import

import mxnet as mx
from mxnet import gluon
from mxnet.gluon import nn
from ...nn.bbox import BBoxCornerToCenter
from ...nn.coder import NormalizedBoxCenterDecoder, MultiPerClassDecoder


class RFCN(gluon.HybridBlock):
    """RCNN network.
    Parameters
    ----------
    features : gluon.HybridBlock
        Base feature extractor before feature pooling layer.
    top_features : gluon.HybridBlock
        Tail feature extractor after feature pooling layer.
    classes : iterable of str
        Names of categories, its length is ``num_class``.
    roi_mode : str
        ROI pooling mode. Currently support 'pool' and 'align'.
    roi_size : tuple of int, length 2
        (height, width) of the ROI region.
    nms_thresh : float, default is 0.3.
        Non-maximum suppression threshold. You can speficy < 0 or > 1 to disable NMS.
    nms_topk : int, default is 400
        Apply NMS to top k detection results, use -1 to disable so that every Detection
         result is used in NMS.
    post_nms : int, default is 100
        Only return top `post_nms` detection results, the rest is discarded. The number is
        based on COCO dataset which has maximum 100 objects per image. You can adjust this
        number if expecting more objects. You can use -1 to return all detections.
    train_patterns : str
        Matching pattern for trainable parameters.
    Attributes
    ----------
    num_class : int
        Number of positive categories.
    classes : iterable of str
        Names of categories, its length is ``num_class``.
    nms_thresh : float
        Non-maximum suppression threshold. You can speficy < 0 or > 1 to disable NMS.
    nms_topk : int
        Apply NMS to top k detection results, use -1 to disable so that every Detection
         result is used in NMS.
    train_patterns : str
        Matching pattern for trainable parameters.
    """
    def __init__(self, features, top_features,
                 classes,
                 short, max_size, train_patterns,
                 nms_thresh, nms_topk, post_nms,
                 roi_mode, roi_size, stride, clip, **kwargs):
        super(RFCN, self).__init__(**kwargs)
        self.classes = classes
        self.num_class = len(classes)
        self.short = short
        self.max_size = max_size
        self.train_patterns = train_patterns
        self.nms_thresh = nms_thresh
        self.nms_topk = nms_topk
        self.post_nms = post_nms

        assert self.num_class > 0, "Invalid number of class : {}".format(self.num_class)
        assert roi_mode.lower() in ['pspool'], "Invalid roi_mode: {}".format(roi_mode)
        self._roi_mode = roi_mode.lower()
        assert len(roi_size) == 2, "Require (h, w) as roi_size, given {}".format(roi_size)
        self._roi_size = roi_size
        self._stride = stride

        with self.name_scope():
            self.features = features
            self.top_features = top_features
            self.conv_new_1 = nn.HybridSequential()
            conv_new_1_conv = nn.Conv2D(1024, 1, 1, 0, weight_initializer=mx.init.Normal(0.01))
            conv_new_1_conv.bias.lr_mult = 2.
            self.conv_new_1.add(conv_new_1_conv)
            self.conv_new_1.add(nn.Activation('relu'))
            #self.conv_new_1 = nn.Conv2D(1024, 1, 1, 0, weight_initializer=mx.init.Normal(0.01))
            self.rfcn_cls = nn.Conv2D((self.num_class+1) * (roi_size[0]**2), 1, 1, 0, weight_initializer=mx.init.Normal(0.01))
            self.rfcn_cls.bias.lr_mult = 2.
            self.rfcn_bbox = nn.Conv2D(4 * (roi_size[0]**2), 1, 1, 0, weight_initializer=mx.init.Normal(0.01))
            self.rfcn_bbox.bias.lr_mult = 2.

            self.cls_decoder = MultiPerClassDecoder(num_class=self.num_class+1)
            self.box_to_center = BBoxCornerToCenter()
            self.box_decoder = NormalizedBoxCenterDecoder(clip=clip)
            # cascade 2nd and 3rd rcnn
            self.conv_new_2 = nn.HybridSequential()
            conv_new_2_conv = nn.Conv2D(1024, 1, 1, 0, weight_initializer=mx.init.Normal(0.01))
            conv_new_2_conv.weight.lr_mult = 2.
            conv_new_2_conv.bias.lr_mult = 4.
            self.conv_new_2.add(conv_new_2_conv)
            self.conv_new_2.add(nn.Activation('relu'))
            # self.conv_new_2 = nn.Conv2D(1024, 1, 1, 0, weight_initializer=mx.init.Normal(0.01))
            self.rfcn_cls_2nd = nn.Conv2D((self.num_class+1) * (roi_size[0]**2), 1, 1, 0, weight_initializer=mx.init.Normal(0.01)) 
            self.rfcn_bbox_2nd = nn.Conv2D(4 * (roi_size[0]**2), 1, 1, 0, weight_initializer=mx.init.Normal(0.01)) 
            self.rfcn_cls_2nd.weight.lr_mult = 2.
            self.rfcn_bbox_2nd.weight.lr_mult = 2.
            self.rfcn_cls_2nd.bias.lr_mult = 4.
            self.rfcn_bbox_2nd.bias.lr_mult = 4.
            self.conv_new_3 = nn.HybridSequential()
            conv_new_3_conv = nn.Conv2D(1024, 1, 1, 0, weight_initializer=mx.init.Normal(0.01))
            conv_new_2_conv.weight.lr_mult = 4.
            conv_new_2_conv.bias.lr_mult = 8.            
            self.conv_new_3.add(conv_new_2_conv)
            self.conv_new_3.add(nn.Activation('relu'))
            self.rfcn_cls_3rd = nn.Conv2D((self.num_class+1) * (roi_size[0]**2), 1, 1, 0, weight_initializer=mx.init.Normal(0.01)) 
            self.rfcn_bbox_3rd = nn.Conv2D(4 * (roi_size[0]**2), 1, 1, 0, weight_initializer=mx.init.Normal(0.01)) 
            self.rfcn_cls_3rd.weight.lr_mult = 4.
            self.rfcn_bbox_3rd.weight.lr_mult = 4.
            self.rfcn_cls_3rd.bias.lr_mult = 8.
            self.rfcn_bbox_3rd.bias.lr_mult = 8.

    def collect_train_params(self, select=None):
        """Collect trainable params.
        This function serves as a help utility function to return only
        trainable parameters if predefined by experienced developer/researcher.
        For example, if cross-device BatchNorm is not enabled, we will definitely
        want to fix BatchNorm statistics to avoid scaling problem because RCNN training
        batch size is usually very small.
        Parameters
        ----------
        select : select : str
            Regular expressions for parameter match pattern
        Returns
        -------
        The selected :py:class:`mxnet.gluon.ParameterDict`
        """
        if select is None:
            return self.collect_params(self.train_patterns)
        return self.collect_params(select)

    def set_nms(self, nms_thresh=0.3, nms_topk=400, post_nms=100):
        """Set NMS parameters to the network.
        .. Note::
            If you are using hybrid mode, make sure you re-hybridize after calling
            ``set_nms``.
        Parameters
        ----------
        nms_thresh : float, default is 0.3.
            Non-maximum suppression threshold. You can speficy < 0 or > 1 to disable NMS.
        nms_topk : int, default is 400
            Apply NMS to top k detection results, use -1 to disable so that every Detection
             result is used in NMS.
        post_nms : int, default is 100
            Only return top `post_nms` detection results, the rest is discarded. The number is
            based on COCO dataset which has maximum 100 objects per image. You can adjust this
            number if expecting more objects. You can use -1 to return all detections.
        Returns
        -------
        None
        """
        self._clear_cached_op()
        self.nms_thresh = nms_thresh
        self.nms_topk = nms_topk
        self.post_nms = post_nms

    # pylint: disable=arguments-differ
    def hybrid_forward(self, F, x, width, height):
        """Not implemented yet."""
        raise NotImplementedError