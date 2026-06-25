# SplatCapture iOS SwiftUI App

This directory contains the Swift source files for **SplatCapture**, a SwiftUI companion app that turns your iPhone into a real-time, interactive 3D Gaussian Splatting scan tool.

It connects directly to your deployed FastAPI backend (e.g. `https://nerf.mattbouchard.com`) to upload frames, trigger reconstruction on the GPU (RunPod), and preview the completed interactive 3D scene directly inside the app using WebGL.

---

## 📂 Source Files Included

1. **`CameraService.swift`**: Wraps `AVFoundation` to handle permission checks, camera feed setup (`AVCaptureSession`), high-quality photo capture, and haptic feedback.
2. **`MainViewModel.swift`**: State management & Networking engine. Handles staged photo indexing, parallel multi-part image uploads with progress reporting, triggering the reconstruction job (`POST /nerfify`), and long-polling the job status (`GET /jobs/{id}`).
3. **`WebViewer.swift`**: A SwiftUI `UIViewRepresentable` wrapping `WKWebView` to display the immersive 3D viewer.
4. **`ContentView.swift`**: The main user interface. Features a sleek, dark-themed viewfinder with guidelines, a slide-up photo review and outlier culling grid, upload progress indicators, and the final 3D interactive viewer with a native Share/Export sheet.

---

## 🛠️ How to Set Up in Xcode

Follow these steps to compile and run the app on your physical iPhone:

### 1. Create a New Xcode Project
- Open Xcode and choose **File > New > Project...**
- Select **iOS > App** and click **Next**.
- Project Name: `SplatCapture`
- Interface: **SwiftUI**
- Language: **Swift**
- Click **Next** and save the project to your local drive.

### 2. Add the Code Files
- Copy the four `.swift` files from this directory (`CameraService.swift`, `MainViewModel.swift`, `WebViewer.swift`, and `ContentView.swift`) and add them into your Xcode project navigator.
- Replace the default template `ContentView.swift` with the custom `ContentView.swift` provided here.

### 3. Configure Camera Permissions (`Info.plist`)
In iOS, you **must** request explicit user permission before starting the camera.
- In your Xcode project settings, navigate to the **Info** tab of your app target.
- Add a new row to the **Custom iOS Target Properties**:
  - Key: `Privacy - Camera Usage Description`
  - Value: `SplatCapture requires access to your camera to capture overlapping photos for 3D Gaussian Splatting reconstruction.`

### 4. Configure App Transport Security (Optional)
If you want to test the app locally using your Mac's development server (e.g., `http://192.168.x.x:8000`), you need to allow local HTTP requests:
- In your project target's **Info** tab, add a new row:
  - Key: `App Transport Security Settings`
  - Under it, add: `Allow Arbitrary Loads` -> `YES`
- *Note: This is not needed for your production Render URL (`https://nerf.mattbouchard.com`), which uses HTTPS by default.*

### 5. Run on a Physical Device
- Connect your iPhone to your Mac via USB.
- Select your iPhone as the target device in Xcode's top bar.
- Choose your developer team under **Signing & Capabilities** to sign the app.
- Hit **Run (⌘R)**!

---

## 📸 How to Perform a Scan

1. **Aim & Target**: Position an object in the center of the dashed guidelines.
2. **Collect Views**: Move slowly around the object, capturing **20 to 40 overlapping photos** from multiple angles. Try to capture a full orbit (e.g. spiral slightly up and down) for optimal COLMAP camera-pose calculation.
3. **Review & Cull**: Tap the bottom-left thumbnail to open the Staged Photos grid. Remove any blurry or out-of-focus photos using the red button.
4. **Select Backend**: Open **Settings (Gear Icon)** to input your server URL and switch between processing strategies:
   - **Local Pipeline** (CPU-based testing)
   - **RunPod GPU** (End-to-end full resolution training)
   - **World Labs** (Marble multimodal world generator)
5. **Reconstruct**: Tap **Reconstruct Scan**! The app will upload the images in parallel, poll the server status dynamically, and open the interactive 3D WebGL viewer as soon as the reconstruction is ready.
6. **Share**: Use the native iOS Share Sheet button at the top-right to copy the link or share the raw 3D model with recruiters, colleagues, or friends!
