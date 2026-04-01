#include "esp_camera.h" // ESP32 Camera library
#include <WiFi.h>       // Wi-Fi library
#include <HTTPClient.h> // HTTP client
#include <HX711.h>      // HX711 library (install via Arduino Library Manager)
#include "esp_heap_caps.h" // For PSRAM allocation

// Wi-Fi credentials (update these)
const char* ssid = "POCO M3";
const char* password = "Anant2005";

// Server details (update server_ip to your laptop's Wi-Fi IP)
const char* server_ip = "192.168.43.223"; // Laptop/server IP
const int server_port = 5000;
const char* post_endpoint = "/upload";

// HX711 pins and calibration
const int LOADCELL_DOUT_PIN = 13;
const int LOADCELL_SCK_PIN = 12;
HX711 scale;
const float calibration_factor = -431; // Adjust based on your load cell calibration

// Button pin
const int BUTTON_PIN = 14;

// Flash LED pin
#define FLASH_LED_PIN 4

// ---------------------------------------------------------
// Camera configuration (optimized for getting latest frame)
// ---------------------------------------------------------
void setupCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pixel_format = PIXFORMAT_JPEG;

  // You can change this if needed (VGA, SVGA, etc.)
  config.frame_size = FRAMESIZE_SXGA;
  config.jpeg_quality = 10;      // 0-63 (higher = more compression)
  config.fb_count = 1;           // *** Single buffer for fresh still captures ***
  config.grab_mode = CAMERA_GRAB_LATEST; // *** Always grab latest frame ***

  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.xclk_freq_hz = 20000000;

  // AI-Thinker pinout
  config.pin_d0 = 5;
  config.pin_d1 = 18;
  config.pin_d2 = 19;
  config.pin_d3 = 21;
  config.pin_d4 = 36;
  config.pin_d5 = 39;
  config.pin_d6 = 34;
  config.pin_d7 = 35;
  config.pin_xclk = 0;
  config.pin_pclk = 22;
  config.pin_vsync = 25;
  config.pin_href = 23;
  config.pin_sccb_sda = 26;
  config.pin_sccb_scl = 27;
  config.pin_pwdn = 32;
  config.pin_reset = -1;

  // Initialize camera
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    while (1) delay(500);
  }

  // Sensor configuration
  sensor_t *s = esp_camera_sensor_get();
  if (s) {
    s->set_vflip(s, 1);
    s->set_hmirror(s, 1);

    s->set_brightness(s, 2);
    s->set_contrast(s, 2);
    s->set_saturation(s, 2);
    s->set_sharpness(s, 2);
    s->set_denoise(s, 0);
    s->set_whitebal(s, 1);
    s->set_awb_gain(s, 1);
    s->set_exposure_ctrl(s, 1);
    s->set_gain_ctrl(s, 1);
    s->set_aec2(s, 1);
    s->set_ae_level(s, 1);
    s->set_gainceiling(s, GAINCEILING_128X);
    s->set_lenc(s, 1);
    s->set_wb_mode(s, 0);
    s->set_special_effect(s, 2); // Grayscale (for debugging)
    Serial.println("Camera sensor configured with enhanced image settings");
  }

  delay(100); // Stabilize
}

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println("ESP32-CAM starting...");

  // PSRAM check (for debugging)
  Serial.printf("PSRAM: %d bytes\n", ESP.getPsramSize());

  // Init flash LED (off)
  pinMode(FLASH_LED_PIN, OUTPUT);
  digitalWrite(FLASH_LED_PIN, LOW);

  // Init button
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  // Connect to Wi-Fi
  WiFi.begin(ssid, password);
  Serial.print("Connecting to Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWi-Fi connected! IP: " + WiFi.localIP().toString());

  // Initialize HX711 and tare
  scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);
  scale.set_scale(calibration_factor);
  scale.tare(20); // Tare with 20 readings, no weight on scale
  Serial.println("Load cell tared.");

  // Initialize camera
  setupCamera();
  Serial.println("Setup complete. Waiting for button press...");
}

void loop() {
  // Wait for button press
  if (digitalRead(BUTTON_PIN) == LOW) {
    delay(50); // Debounce
    if (digitalRead(BUTTON_PIN) == LOW) {
      // Wait for release to prevent retrigger
      while (digitalRead(BUTTON_PIN) == LOW) {
        delay(10);
      }
      Serial.println("Button pressed. Starting process...");

      // ------------------ Step 1: Measure weight ------------------
      float weight = scale.get_units(10); // Average 10 readings
      if (weight < 0) weight = 0;         // Clamp negative values
      Serial.printf("Measured weight: %.2f g\n", weight);

      // ------------------ Step 2: Capture image ------------------
      digitalWrite(FLASH_LED_PIN, HIGH);  // Flash ON
      delay(300);                         // Small warm-up

      sensor_t *s = esp_camera_sensor_get();

      // *** Flush old frames to avoid sending previous image ***
      for (int i = 0; i < 3; i++) {
        camera_fb_t *tmp = esp_camera_fb_get();
        if (tmp) {
          esp_camera_fb_return(tmp);
        }
        delay(50);
      }

      // Lock exposure before final capture
      if (s) {
        s->set_exposure_ctrl(s, 0); // Lock the current exposure
      }

      camera_fb_t *fb = esp_camera_fb_get();
      if (!fb) {
        Serial.println("Capture failed");
        digitalWrite(FLASH_LED_PIN, LOW);
        if (s) s->set_exposure_ctrl(s, 1); // Unlock
        return;
      }

      Serial.printf("Capture OK! Size: %u bytes\n", fb->len);

      // Turn flash off after capture
      digitalWrite(FLASH_LED_PIN, LOW);
      if (s) s->set_exposure_ctrl(s, 1); // Unlock exposure

      // ------------------ Step 3: Send weight + image ------------------
      if (WiFi.status() == WL_CONNECTED) {
        HTTPClient http;
        String url = "http://" + String(server_ip) + ":" + String(server_port) + String(post_endpoint);
        http.begin(url);

        // Multipart form data
        String boundary = "----ESP32Boundary" + String(random(1000));
        String head = "--" + boundary + "\r\n";

        // weight field
        String weight_part =
          head +
          "Content-Disposition: form-data; name=\"weight\"\r\n\r\n" +
          String(weight, 2) + "\r\n";

        // image field
        String image_part =
          head +
          "Content-Disposition: form-data; name=\"image\"; filename=\"capture.jpg\"\r\n"
          "Content-Type: image/jpeg\r\n\r\n";

        String tail = "\r\n--" + boundary + "--\r\n";

        size_t weight_part_len = weight_part.length();
        size_t image_part_len = image_part.length();
        size_t tail_len = tail.length();
        size_t total_len = weight_part_len + image_part_len + fb->len + tail_len;

        uint8_t* multipart_data = (uint8_t*)heap_caps_malloc(
          total_len, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT
        );

        if (multipart_data) {
          uint8_t* ptr = multipart_data;

          memcpy(ptr, weight_part.c_str(), weight_part_len);
          ptr += weight_part_len;

          memcpy(ptr, image_part.c_str(), image_part_len);
          ptr += image_part_len;

          // *** Copy image bytes into multipart buffer ***
          memcpy(ptr, fb->buf, fb->len);
          ptr += fb->len;

          memcpy(ptr, tail.c_str(), tail_len);

          // *** Return camera buffer ASAP so camera can refresh ***
          esp_camera_fb_return(fb);
          fb = nullptr;

          http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);
          Serial.println("Sending weight and image...");
          int code = http.POST(multipart_data, total_len);
          if (code > 0) {
            Serial.printf("Send OK! Code: %d\n", code);
          } else {
            Serial.printf("Send failed: %s (Code: %d)\n", http.errorToString(code).c_str(), code);
          }
          http.end();
          heap_caps_free(multipart_data);
        } else {
          Serial.println("Failed to allocate memory for multipart data");
          // We must still return fb if not returned yet
          if (fb) {
            esp_camera_fb_return(fb);
            fb = nullptr;
          }
        }
      } else {
        Serial.println("Wi-Fi lost; can't send");
        // Return frame buffer if Wi-Fi problem
        if (fb) {
          esp_camera_fb_return(fb);
          fb = nullptr;
        }
      }

      // ------------------ Step 4: Done ------------------
      delay(100);
      Serial.println("Process complete. Waiting for next button press...");
    }
  }

  delay(100); // Prevent watchdog and save power
}
