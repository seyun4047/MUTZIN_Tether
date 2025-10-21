import requests
import json

api_url = "<yourapiurl>prod/generate-url"
payload = {"filename": "test_photo.jpg"}

response = requests.post(api_url, json=payload)
print(response.status_code)
print(response.json())  # presigned_url 확인
