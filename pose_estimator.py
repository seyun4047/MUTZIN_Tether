import cv2
import mediapipe as mp
import numpy as np
import json
import os
from datetime import datetime

class PoseEstimator:
    def __init__(self):
        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose(static_image_mode=True, min_detection_confidence=0.5)
        self.mp_drawing = mp.solutions.drawing_utils

    def classify_pose(self, landmarks, image_shape):
        h, w = image_shape[:2]
        # 각 주요 랜드마크 인덱스 (MediaPipe 기준)
        LEFT_SHOULDER = 11
        RIGHT_SHOULDER = 12
        LEFT_HIP = 23
        RIGHT_HIP = 24
        LEFT_KNEE = 25
        RIGHT_KNEE = 26
        LEFT_ANKLE = 27
        RIGHT_ANKLE = 28

        # 각 랜드마크의 픽셀 좌표 추출
        def get_point(idx):
            lm = landmarks[idx]
            return np.array([lm.x * w, lm.y * h])

        # 1. 상/하반신 랜드마크 감지 여부
        detected_idxs = [i for i, lm in enumerate(landmarks) if lm.visibility > 0.5]
        has_legs = (LEFT_KNEE in detected_idxs or RIGHT_KNEE in detected_idxs) and \
                   (LEFT_ANKLE in detected_idxs or RIGHT_ANKLE in detected_idxs)
        upper_body_only = not has_legs

        # 2. 서있음/앉음/누움 판별
        try:
            left_shoulder = get_point(LEFT_SHOULDER)
            right_shoulder = get_point(RIGHT_SHOULDER)
            left_hip = get_point(LEFT_HIP)
            right_hip = get_point(RIGHT_HIP)
            left_knee = get_point(LEFT_KNEE)
            right_knee = get_point(RIGHT_KNEE)
            left_ankle = get_point(LEFT_ANKLE)
            right_ankle = get_point(RIGHT_ANKLE)

            # 좌우 평균으로 중심선 계산
            shoulder_center = (left_shoulder + right_shoulder) / 2
            hip_center = (left_hip + right_hip) / 2
            knee_center = (left_knee + right_knee) / 2
            ankle_center = (left_ankle + right_ankle) / 2

            # 상체 기울기
            torso_vec = hip_center - shoulder_center
            torso_angle = np.arctan2(torso_vec[1], torso_vec[0]) * 180 / np.pi

            # 몸의 세로 길이와 무릎-엉덩이 거리
            torso_len = np.linalg.norm(shoulder_center - hip_center)
            thigh_len = np.linalg.norm(hip_center - knee_center)

            if abs(torso_angle) < 30:  # 수평에 가까움 (누움)
                pose_type = "lying"
            elif abs(torso_angle) > 60:  # 수직에 가까움 (섬/앉음)
                if thigh_len < torso_len * 0.7:
                    pose_type = "sitting"
                else:
                    pose_type = "standing"
            else:
                pose_type = "unknown"
        except Exception:
            pose_type = "unknown"

        # 3. 뷰(정면/측면/뒷모습) 판별
        left_shoulder_x = landmarks[LEFT_SHOULDER].x
        right_shoulder_x = landmarks[RIGHT_SHOULDER].x
        shoulder_dist = abs(left_shoulder_x - right_shoulder_x)
        if shoulder_dist > 0.3:
            view_type = "front"
        elif shoulder_dist < 0.1:
            view_type = "side"
        else:
            view_type = "back"

        return {
            "pose_type": pose_type,
            "view_type": view_type,
            "upper_body_only": upper_body_only
        }

    def estimate(self, image_path):
        """
        이미지에서 자세를 추정합니다.

        Returns:
            dict: {
                'pose': str,  # "standing", "sitting", "lying", "unknown"
                'view': str,  # "front", "side", "back"
                'full_body': bool  # True if full body is visible
            }
        """
        try:
            image = cv2.imread(image_path)
            if image is None:
                raise Exception("이미지를 불러올 수 없습니다.")

            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            results = self.pose.process(image_rgb)

            if not results.pose_landmarks:
                raise Exception("사람을 찾지 못했습니다.")

            # 자세 분류 수행
            classification = self.classify_pose(results.pose_landmarks.landmark, image.shape)

            # 결과 반환
            return {
                'pose': classification['pose_type'],
                'view': classification['view_type'],
                'full_body': not classification['upper_body_only']
            }

        except Exception as e:
            print(f"자세 추정 오류: {str(e)}")
            return {
                'pose': 'unknown',
                'view': 'unknown',
                'full_body': False
            }

    def get_formatted_result(self, results):
        """자세 추정 결과를 포맷팅된 문자열로 반환"""
        pose_desc = {
            'standing': 'Standing',
            'sitting': 'Sitting',
            'lying': 'Lying',
            'unknown': 'Unknown'
        }

        view_desc = {
            'front': 'Front',
            'side': 'Side',
            'back': 'Back',
            'unknown': 'Unknown'
        }

        return (f"Pose: {pose_desc.get(results['pose'], 'Unknown')} | "
                f"View: {view_desc.get(results['view'], 'Unknown')} | "
                f"Body: {'Full body' if results['full_body'] else 'Upper body only'}")