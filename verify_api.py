import requests

try:
    # Assuming runserver is on 8000
    res = requests.get('http://127.0.0.1:8000/api/products/categories/')
    print(f"Status Code: {res.status_code}")
    if res.status_code == 200:
        data = res.json()
        if data:
            first = data[0]
            print("\nFirst Category Data:")
            for k, v in first.items():
                print(f"{k}: {v}")
            if 'image' in first:
                print("\nSUCCESS: 'image' field is present in the response.")
            else:
                print("\nFAILURE: 'image' field is MISSING in the response.")
        else:
            print("No categories found.")
except Exception as e:
    print(f"Error connecting to API: {e}")
鼓
