import requests
import json

api_url = "https://<yourapiurl>/prod/generate-url"
payload = {"filename": "test1.jpg"}

file_path = "../test.jpg"
response = requests.post(api_url, json=payload)
print(response.status_code)
print(response.json())  # presigned_url 확인
presigned_url= response.json()['presigned_url']
print(presigned_url)

with open(file_path, "rb") as f:
    response = requests.put(
        presigned_url,
        data=f,
        headers={"Content-Type": "image/jpeg"}
    )

if response.status_code == 200:
    print("업로드 성공!")
else:
    print("업로드 실패:", response.status_code, response.text)
