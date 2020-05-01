import tensorflow as tf
import numpy as np

def generate_base_anchors(hyper_params):
    """Generating top left anchors for given anchor_ratios, anchor_scales and stride values.
    inputs:
        hyper_params = dictionary

    outputs:
        base_anchors = (anchor_count, [y1, x1, y2, x2])
            these values not normalized yet
    """
    stride = hyper_params["stride"]
    anchor_ratios = hyper_params["anchor_ratios"]
    anchor_scales = hyper_params["anchor_scales"]
    center = stride // 2
    base_anchors = []
    for scale in anchor_scales:
        for ratio in anchor_ratios:
            box_area = scale ** 2
            w = round((box_area / ratio) ** 0.5)
            h = round(w * ratio)
            x_min = center - w / 2
            y_min = center - h / 2
            x_max = center + w / 2
            y_max = center + h / 2
            base_anchors.append([y_min, x_min, y_max, x_max])
    return np.array(base_anchors, dtype=np.float32)

def generate_anchors(hyper_params):
    """Broadcasting base_anchors and generating all anchors for given image parameters.
    inputs:
        hyper_params = dictionary

    outputs:
        anchors = (output_width * output_height * anchor_count, [y1, x1, y2, x2])
            these values in normalized format between [0, 1]
    """
    img_size = hyper_params["img_size"]
    anchor_count = hyper_params["anchor_count"]
    stride = hyper_params["stride"]
    output_height, output_width = img_size // stride, img_size // stride
    #
    grid_x = np.arange(0, output_width) * stride
    grid_y = np.arange(0, output_height) * stride
    #
    width_padding = (img_size - output_width * stride) / 2
    height_padding = (img_size - output_height * stride) / 2
    grid_x = width_padding + grid_x
    grid_y = height_padding + grid_y
    #
    grid_y, grid_x = np.meshgrid(grid_y, grid_x)
    grid_map = np.vstack((grid_y.ravel(), grid_x.ravel(), grid_y.ravel(), grid_x.ravel())).transpose()
    #
    base_anchors = generate_base_anchors(hyper_params)
    #
    output_area = grid_map.shape[0]
    anchors = base_anchors.reshape((1, anchor_count, 4)) + \
              grid_map.reshape((1, output_area, 4)).transpose((1, 0, 2))
    anchors = anchors.reshape((output_area * anchor_count, 4)).astype(np.float32)
    anchors = normalize_bboxes(anchors, float(img_size), float(img_size))
    anchors = tf.clip_by_value(anchors, 0, 1)
    return anchors

def non_max_suppression(pred_bboxes, pred_labels, **kwargs):
    """Applying non maximum suppression.
    Details could be found on tensorflow documentation.
    https://www.tensorflow.org/api_docs/python/tf/image/combined_non_max_suppression
    inputs:
        pred_bboxes = (batch_size, total_bboxes, total_labels, [y1, x1, y2, x2])
            total_labels should be 1 for binary operations like in rpn
        pred_labels = (batch_size, total_bboxes, total_labels)
        **kwargs = other parameters

    outputs:
        nms_boxes = (batch_size, max_detections, [y1, x1, y2, x2])
        nmsed_scores = (batch_size, max_detections)
        nmsed_classes = (batch_size, max_detections)
        valid_detections = (batch_size)
            Only the top valid_detections[i] entries in nms_boxes[i], nms_scores[i] and nms_class[i] are valid.
            The rest of the entries are zero paddings.
    """
    return tf.image.combined_non_max_suppression(
        pred_bboxes,
        pred_labels,
        **kwargs
    )

def get_bboxes_from_deltas(anchors, deltas):
    """Calculating bounding boxes for given bounding box and delta values.
    inputs:
        anchors = (batch_size, total_bboxes, [y1, x1, y2, x2])
        deltas = (batch_size, total_bboxes, [delta_y, delta_x, delta_h, delta_w])

    outputs:
        final_boxes = (batch_size, total_bboxes, [y1, x1, y2, x2])
    """
    all_anc_width = anchors[..., 3] - anchors[..., 1]
    all_anc_height = anchors[..., 2] - anchors[..., 0]
    all_anc_ctr_x = anchors[..., 1] + 0.5 * all_anc_width
    all_anc_ctr_y = anchors[..., 0] + 0.5 * all_anc_height
    #
    all_bbox_width = tf.exp(deltas[..., 3]) * all_anc_width
    all_bbox_height = tf.exp(deltas[..., 2]) * all_anc_height
    all_bbox_ctr_x = (deltas[..., 1] * all_anc_width) + all_anc_ctr_x
    all_bbox_ctr_y = (deltas[..., 0] * all_anc_height) + all_anc_ctr_y
    #
    y1 = all_bbox_ctr_y - (0.5 * all_bbox_height)
    x1 = all_bbox_ctr_x - (0.5 * all_bbox_width)
    y2 = all_bbox_height + y1
    x2 = all_bbox_width + x1
    #
    return tf.stack([y1, x1, y2, x2], axis=-1)

def get_deltas_from_bboxes(bboxes, gt_boxes):
    """Calculating bounding box deltas for given bounding box and ground truth boxes.
    inputs:
        bboxes = (batch_size, total_bboxes, [y1, x1, y2, x2])
        gt_boxes = (batch_size, total_bboxes, [y1, x1, y2, x2])

    outputs:
        final_deltas = (batch_size, total_bboxes, [delta_y, delta_x, delta_h, delta_w])
    """
    bbox_width = bboxes[..., 3] - bboxes[..., 1]
    bbox_height = bboxes[..., 2] - bboxes[..., 0]
    bbox_ctr_x = bboxes[..., 1] + 0.5 * bbox_width
    bbox_ctr_y = bboxes[..., 0] + 0.5 * bbox_height
    #
    gt_width = gt_boxes[..., 3] - gt_boxes[..., 1]
    gt_height = gt_boxes[..., 2] - gt_boxes[..., 0]
    gt_ctr_x = gt_boxes[..., 1] + 0.5 * gt_width
    gt_ctr_y = gt_boxes[..., 0] + 0.5 * gt_height
    #
    bbox_width = tf.where(tf.equal(bbox_width, 0), 1e-3, bbox_width)
    bbox_height = tf.where(tf.equal(bbox_height, 0), 1e-3, bbox_height)
    delta_x = tf.where(tf.equal(gt_width, 0), tf.zeros_like(gt_width), tf.truediv((gt_ctr_x - bbox_ctr_x), bbox_width))
    delta_y = tf.where(tf.equal(gt_height, 0), tf.zeros_like(gt_height), tf.truediv((gt_ctr_y - bbox_ctr_y), bbox_height))
    delta_w = tf.where(tf.equal(gt_width, 0), tf.zeros_like(gt_width), tf.math.log(gt_width / bbox_width))
    delta_h = tf.where(tf.equal(gt_height, 0), tf.zeros_like(gt_height), tf.math.log(gt_height / bbox_height))
    #
    return tf.stack([delta_y, delta_x, delta_h, delta_w], axis=-1)

def generate_iou_map(bboxes, gt_boxes):
    """Calculating iou values for each ground truth boxes in batched manner.
    inputs:
        bboxes = (batch_size, total_bboxes, [y1, x1, y2, x2])
        gt_boxes = (batch_size, total_gt_boxes, [y1, x1, y2, x2])

    outputs:
        iou_map = (batch_size, total_bboxes, total_gt_boxes)
    """
    bbox_y1, bbox_x1, bbox_y2, bbox_x2 = tf.split(bboxes, 4, axis=-1)
    gt_y1, gt_x1, gt_y2, gt_x2 = tf.split(gt_boxes, 4, axis=-1)
    # Calculate bbox and ground truth boxes areas
    gt_area = tf.squeeze((gt_y2 - gt_y1) * (gt_x2 - gt_x1), axis=-1)
    bbox_area = tf.squeeze((bbox_y2 - bbox_y1) * (bbox_x2 - bbox_x1), axis=-1)
    #
    x_top = tf.maximum(bbox_x1, tf.transpose(gt_x1, [0, 2, 1]))
    y_top = tf.maximum(bbox_y1, tf.transpose(gt_y1, [0, 2, 1]))
    x_bottom = tf.minimum(bbox_x2, tf.transpose(gt_x2, [0, 2, 1]))
    y_bottom = tf.minimum(bbox_y2, tf.transpose(gt_y2, [0, 2, 1]))
    ### Calculate intersection area
    intersection_area = tf.maximum(x_bottom - x_top, 0) * tf.maximum(y_bottom - y_top, 0)
    ### Calculate union area
    union_area = (tf.expand_dims(bbox_area, -1) + tf.expand_dims(gt_area, 1) - intersection_area)
    # Intersection over Union
    return intersection_area / union_area

def normalize_bboxes(bboxes, height, width):
    """Normalizing bounding boxes.
    inputs:
        bboxes = (batch_size, total_bboxes, [y1, x1, y2, x2])
        height = image height
        width = image width
    outputs:
        normalized_bboxes = (batch_size, total_bboxes, [y1, x1, y2, x2])
            in normalized form [0, 1]
    """
    y1 = bboxes[..., 0] / height
    x1 = bboxes[..., 1] / width
    y2 = bboxes[..., 2] / height
    x2 = bboxes[..., 3] / width
    return tf.stack([y1, x1, y2, x2], axis=-1)

def denormalize_bboxes(bboxes, height, width):
    """Denormalizing bounding boxes.
    inputs:
        bboxes = (batch_size, total_bboxes, [y1, x1, y2, x2])
            in normalized form [0, 1]
        height = image height
        width = image width
    outputs:
        denormalized_bboxes = (batch_size, total_bboxes, [y1, x1, y2, x2])
    """
    y1 = bboxes[..., 0] * height
    x1 = bboxes[..., 1] * width
    y2 = bboxes[..., 2] * height
    x2 = bboxes[..., 3] * width
    return tf.round(tf.stack([y1, x1, y2, x2], axis=-1))
