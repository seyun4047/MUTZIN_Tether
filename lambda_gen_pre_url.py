# # IAM권한 아래꺼 하거나 혹은 AmazonS3FullAccess
# {
#   "Version": "2012-10-17",
#   "Statement": [
#     {
#       "Effect": "Allow",
#       "Action": ["s3:PutObject", "s3:PutObjectAcl"],
#       "Resource": "arn:aws:s3:::<your-buckert>/*"
#     }
#   ]
# }

import json
import boto3
import os

s3_client = boto3.client('s3')
BUCKET_NAME = os.environ['S3_BUCKET'] #S3_BUCKET 환경변수 추가

def lambda_handler(event, context):
    try:
        # body가 문자열로 전달되므로 JSON 파싱
        body = event.get('body')
        if body:
            body_json = json.loads(body)
        else:
            body_json = {}

        filename = body_json.get('filename')
        if not filename:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "filename required"})
            }

        presigned_url = s3_client.generate_presigned_url(
            ClientMethod='put_object',
            Params={
                'Bucket': BUCKET_NAME,
                'Key': filename,
                'ContentType': 'image/jpeg'
            },
            ExpiresIn=3600
        )

        return {
            "statusCode": 200,
            "body": json.dumps({"presigned_url": presigned_url})
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
