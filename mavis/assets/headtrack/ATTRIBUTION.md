# Head-tracking model

`face_detection_yunet_2023mar.onnx` — **YuNet**, OpenCV's lightweight face
detector, from the OpenCV Model Zoo:
https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet

- Licence: **MIT** (opencv_zoo `models/face_detection_yunet/LICENSE`), which
  permits redistribution, so unlike the avatar models it is committed.
- Authors: Shiqi Yu, Yuantao Feng and contributors. Paper: Wu, Peng & Yu,
  "YuNet: A Tiny Millisecond-level Face Detector", *Machine Intelligence
  Research* 20, 656–665 (2023).
- sha256 `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`
  (232,589 bytes).

Re-fetch (the plain `github.com/.../raw/` URL serves a Git LFS pointer, not
the model — use the LFS media host):

    curl -L -o assets/headtrack/face_detection_yunet_2023mar.onnx \
      https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
    shasum -a 256 assets/headtrack/face_detection_yunet_2023mar.onnx

Loaded by `avatar/headtrack.py` through `cv2.FaceDetectorYN`.
