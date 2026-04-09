import os
import json
import time
from flask import Flask, request
import google.generativeai as genai
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests

# ------------------- CONFIG -------------------
GEMINI_API_KEY = "AIzaSyC_9QNIk_likf5B2ph2Pxm0Z2QgXS6SdQQ"  # Your API key
DISTANCEMATRIX_API_KEY = "L1fDShZvYFwpK4iZIn5IzZ7rj1kdrDs5tYrbl8liQZc1IoCRpkLwUONBIqeOF5Vb"  # Replace with your DistanceMatrix.ai API key. To set up: Sign up at https://distancematrix.ai/, verify email, and get your free API key (1,000 elements/month free). No credit card required.
WEBPAGE_URL = "https://booking-website-ginj.onrender.com/"

# Flask app
app = Flask(__name__)

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)

@app.route('/upload', methods=['POST'])
def upload_image():
    # -------- Debug incoming request --------
    print("Request headers:", request.headers)
    print("Request files:", request.files)
    print("Request content-type:", request.content_type)

    # -------- Receive image from ESP32-CAM --------
    image_bytes = None
    if 'image' in request.files:
        print("Found 'image' in request.files")
        image_file = request.files['image']
        image_bytes = image_file.read()  # Read in-memory bytes
    else:
        # Fallback: Try reading raw request body
        print("No 'image' field, attempting to read raw body")
        if request.content_type.startswith('image/jpeg'):
            image_bytes = request.get_data()
        else:
            print("Invalid content-type or no image data")
            return "No image file received or invalid content-type", 400

    print(f"Received image, size: {len(image_bytes)} bytes")

    # -------- Send image to Gemini API --------
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")  # Updated model
        prompt = (
            "You are an expert Indian postal address extractor and corrector. "
"Carefully read the image (which may contain handwritten or printed sender and receiver addresses). "

"STEP 1: Perform highly accurate OCR extraction. "

"STEP 2: Apply intelligent auto-correction for common Indian address spelling mistakes, typos, and formatting issues "
"(examples: 'Banglore'→'Bengaluru', 'Hydrabad'→'Hyderabad', 'Mumbi'→'Mumbai', 'Delhii'→'Delhi', 'Colny'→'Colony', 'Sociaty'→'Society', "
"'Street'/'Strret'→'Street', 'Road'/'Rod'→'Road', 'Ngr'→'Nagar', 'Vihar'/'Viharh'→'Vihar', 'Phase'/'Phse'→'Phase', "
"'Apartment'/'Appartment'→'Apartment', 'Near'/'Ner'→'Near', etc.). "

"Also standardize common abbreviations intelligently (e.g., 'Rd' → 'Road', 'St' → 'Street', 'Col' → 'Colony' only if it makes sense). "

"CRITICAL RULE: Do NOT change the actual meaning or add extra information — only fix spelling, typos, and minor formatting for better postal delivery. "
"If the text is unclear, make your best reasonable correction based on common Indian address patterns. "

"Ensure strict consistency rules: "
"- City and State must always match logically. "
"- If mismatch occurs, correct based on best logical assumption using Indian geography knowledge. "

"PIN CODE INTELLIGENCE (VERY STRICT - MUST FOLLOW): "
"1. If a valid PIN code is present → Use it to validate and correct City and State. "
"2. If PIN code is missing OR invalid OR incomplete → You MUST infer the correct PIN using City + State. "
"3. ALWAYS choose the most commonly used / central / head post office (GPO) PIN for that city. "
"4. NEVER choose rare or locality-specific PINs. "
"5. ENSURE the PIN strictly belongs to the correct state. "
"6. Examples (must follow pattern): "
"   Bengaluru, Karnataka → 560001 "
"   Hyderabad, Telangana → 500001 "
"   Mumbai, Maharashtra → 400001 "
"   Chennai, Tamil Nadu → 600001 "
"   Delhi → 110001 "
"   Pune, Maharashtra → 411001 "

"PARTIAL / INCORRECT PIN CORRECTION (MANDATORY): "
"- If PIN has OCR mistakes (e.g., '5600O1', '56OOO1', '56010', etc.), you MUST fix it. "
"- Use pattern recognition (digits only, 6-digit format) + City/State context. "
"- Replace common OCR errors like 'O' → '0', 'I' → '1'. "
"- If still ambiguous → fallback to correct central PIN of that city. "

"Mobile number rules: "
"- Extract only valid 10-digit Indian numbers. "
"- Remove spaces, country codes (+91), or formatting. "

"FINAL OUTPUT RULES (STRICT): "
"- Output ONLY clean JSON. "
"- No explanations, no markdown, no extra text. "
"- Ensure all corrected fields are logically consistent and complete. "

"Use exactly this structure:\n\n"
"{'from': {'first_name': '', 'last_name': '', 'address': '', 'city': '', 'state': '', 'pincode': '', 'mobile': ''}, "
"'to': {'first_name': '', 'last_name': '', 'address': '', 'city': '', 'state': '', 'pincode': '', 'mobile': ''}}"
        )
        
        response = model.generate_content([
            {"mime_type": "image/jpeg", "data": image_bytes},
            {"text": prompt}
        ])
    except Exception as e:
        print(f"Gemini API error: {e}")
        return f"Error calling Gemini API: {e}", 500

    # -------- Parse Gemini response --------
    try:
        json_str = response.text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(json_str)
        print("Parsed JSON:", json.dumps(data, indent=2))
    except Exception as e:
        print("Gemini raw output:", response.text)
        return f"Error parsing Gemini response: {e}", 500

    # -------- Calculate distance using DistanceMatrix.ai API --------
    try:
        origin = f"{data['from']['address']}, {data['from']['city']}, {data['from']['state']} {data['from']['pincode']}"
        destination = f"{data['to']['address']}, {data['to']['city']}, {data['to']['state']} {data['to']['pincode']}"
        print("Origin:", origin)
        print("Destination:", destination)
        params = {
            'origins': origin,
            'destinations': destination,
            'key': DISTANCEMATRIX_API_KEY,
            'mode': 'driving'
        }
        maps_response = requests.get("https://api.distancematrix.ai/maps/api/distancematrix/json", params=params)
        print("Maps response status:", maps_response.status_code)
        maps_data = maps_response.json()
        print("Maps full response:", json.dumps(maps_data, indent=2))
        if maps_data.get('status') != 'OK' or maps_data.get('rows', [{}])[0].get('elements', [{}])[0].get('status') != 'OK':
            raise ValueError(f"Error in DistanceMatrix.ai API response: {maps_data.get('status')} - {maps_data.get('error_message', '')}")
        distance_meters = maps_data['rows'][0]['elements'][0]['distance']['value']
        distance_km = distance_meters / 1000  # Convert to km
        duration_seconds = maps_data['rows'][0]['elements'][0]['duration']['value']
        # For now, we only use distance for the form; duration could be used elsewhere if needed
        print(f"Calculated distance: {distance_km} km, duration: {duration_seconds} seconds")
    except Exception as e:
        print(f"DistanceMatrix.ai API error: {e}")
        return f"Error calculating distance: {e}", 500

    # -------- Selenium automation --------
    try:
        driver = webdriver.Chrome()  # Assumes ChromeDriver in PATH
        driver.get(WEBPAGE_URL)
        wait = WebDriverWait(driver, 10)
        weight = request.form.get('weight', '450')

        # Wait for sender-first input to load
        wait.until(EC.presence_of_element_located((By.ID, "sender-first")))

        # -------- Fill Sender Fields --------
        driver.find_element(By.ID, "sender-first").send_keys(data["from"]["first_name"])
        driver.find_element(By.ID, "sender-last").send_keys(data["from"]["last_name"])
        driver.find_element(By.ID, "sender-addr1").send_keys(data["from"]["address"])
        driver.find_element(By.ID, "sender-city").send_keys(data["from"]["city"])
        driver.find_element(By.ID, "sender-state").send_keys(data["from"]["state"])
        driver.find_element(By.ID, "sender-pin").send_keys(data["from"]["pincode"])
        driver.find_element(By.ID, "sender-mobile").send_keys(data["from"]["mobile"])

        # -------- Fill Recipient Fields --------
        driver.find_element(By.ID, "recipient-first").send_keys(data["to"]["first_name"])
        driver.find_element(By.ID, "recipient-last").send_keys(data["to"]["last_name"])
        driver.find_element(By.ID, "recipient-addr1").send_keys(data["to"]["address"])
        driver.find_element(By.ID, "recipient-city").send_keys(data["to"]["city"])
        driver.find_element(By.ID, "recipient-state").send_keys(data["to"]["state"])
        driver.find_element(By.ID, "recipient-pin").send_keys(data["to"]["pincode"])
        driver.find_element(By.ID, "recipient-mobile").send_keys(data["to"]["mobile"])

        # -------- Fill Calculated Distance & Dummy Weight --------
        driver.find_element(By.ID, "distance-input").send_keys(str(int(distance_km)))
        driver.find_element(By.ID, "weight").send_keys(weight)

        # -------- Click Calculate --------
        driver.find_element(By.ID, "calculate-btn").click()

        # Wait for results
        time.sleep(5)

        # Keep browser open for debugging
        # driver.quit()

    except Exception as e:
        print(f"Selenium error: {e}")
        return f"Error in Selenium automation: {e}", 500

    return "✅ Form filled and Calculate clicked successfully", 200

# -------- Run Flask server --------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

