# SplatCapture iOS

SplatCapture is a SwiftUI companion app that turns an iPhone into an interactive 3D
Gaussian Splatting scanner. It captures overlapping photos, uploads them to the
nerf-service FastAPI backend, triggers GPU reconstruction (RunPod), and previews the
finished scene in-app with a WebGL viewer.

It talks to the deployed API (default `https://nerf.mattbouchard.com`) using the
asynchronous submit -> poll -> download contract: `POST /upload`, `POST /nerfify` (202),
`GET /jobs/{id}`, `GET /jobs/{id}/result`, and `/viewer?url=...`.

---

## Source files

| File | Responsibility |
|------|----------------|
| `SplatCaptureApp.swift` | `@main` app entry point. |
| `CameraService.swift` | `AVCaptureSession` setup, permission handling, high-resolution photo capture (via `maxPhotoDimensions`), haptics. Publishes each capture through a Combine `PassthroughSubject`. |
| `MainViewModel.swift` | State + networking: ordered parallel uploads, `/nerfify`, job polling, viewer URL construction. Persists the server URL across launches. |
| `WebViewer.swift` | `UIViewRepresentable` wrapping `WKWebView` for the 3D viewer. |
| `ContentView.swift` | Dark-themed viewfinder, staged-photo review/cull grid, progress HUD, 3D viewer, and share sheet. |

---

## Build and run

The project is generated from `project.yml` with [XcodeGen](https://github.com/yonaskolb/XcodeGen),
so the `.xcodeproj` is reproducible and not checked in.

### 1. Install XcodeGen (one time)

```bash
brew install xcodegen
```

(Requires full **Xcode** from the App Store — Command Line Tools alone cannot build an iOS app.)

### 2. Generate the project

```bash
cd nerf-service/SplatCapture-iOS
xcodegen
open SplatCapture.xcodeproj
```

`xcodegen` reads `project.yml` and writes `SplatCapture.xcodeproj`. Re-run it whenever you
add/remove source files or change build settings. Regenerate any time after pulling.

### 3. Configure signing and run

- In Xcode, select the **SplatCapture** target > **Signing & Capabilities** and choose your
  development team.
- Connect a physical iPhone (the camera does not work in the Simulator), select it as the run
  destination, and press **Run (Cmd-R)**.

### What `project.yml` already configures

- iOS 17 deployment target, portrait orientation, bundle id `com.mattbouchard.splatcapture`.
- `NSCameraUsageDescription` (the camera permission prompt) — no manual Info.plist editing needed.
- `NSAppTransportSecurity > NSAllowsLocalNetworking` so you can test against a Mac dev server over
  HTTP on your LAN (e.g. `http://192.168.x.x:8000`). Production over HTTPS is unaffected.

---

## Performing a scan

1. **Aim**: center the subject in the dashed guideline.
2. **Capture**: move slowly around the subject, taking **20-40 overlapping photos** from multiple
   angles (a full orbit, spiraling slightly up and down, gives COLMAP the best pose coverage).
3. **Review & cull**: tap the bottom-left thumbnail to open the staged-photos grid and remove blurry
   frames.
4. **Endpoint**: open **Settings (gear)** to set the server URL. The active compute backend is
   decided server-side (`NERF_BACKEND`); tap **Refresh from /healthz** to see which is running.
5. **Reconstruct**: tap **Reconstruct Scan**. The app uploads in parallel (preserving capture order),
   polls job status, and opens the interactive 3D viewer when the result is ready.
6. **Share**: use the share button to send the result link.

---

## Notes

- A minimum of 3 frames is required; the app caps staging at 80.
- The in-app 3D preview loads `/viewer?url=<result>`, which fetches the `.ply` from object storage.
  If the viewer is blank in production, confirm the R2 bucket allows CORS from
  `nerf.mattbouchard.com`.
- World Labs mode (`result_format == "world"`) opens the Marble world URL directly instead of the
  WebGL `.ply` viewer.
