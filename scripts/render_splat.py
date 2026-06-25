"""Render a 3DGS .ply to a clean PNG (alpha-weighted point splatting, PCA-framed)."""
import sys
import numpy as np
from PIL import Image

PLY = sys.argv[1] if len(sys.argv) > 1 else "client/scene.ply"
SH_C0 = 0.28209479177387814


def load(path):
    f = open(path, "rb")
    hdr = b""
    while b"end_header" not in hdr:
        hdr += f.readline()
    names = []
    for line in hdr.decode("ascii", "replace").splitlines():
        if line.startswith("property float"):
            names.append(line.split()[-1])
    n = int([l for l in hdr.decode().splitlines() if l.startswith("element vertex")][0].split()[-1])
    data = np.frombuffer(f.read(n * len(names) * 4), dtype=np.float32).reshape(n, len(names))
    col = {name: i for i, name in enumerate(names)}
    xyz = data[:, [col["x"], col["y"], col["z"]]].astype(np.float64)
    fdc = data[:, [col["f_dc_0"], col["f_dc_1"], col["f_dc_2"]]]
    rgb = np.clip(0.5 + SH_C0 * fdc, 0, 1)
    alpha = 1.0 / (1.0 + np.exp(-data[:, col["opacity"]]))
    return xyz, rgb, alpha


def render(xyz, rgb, alpha, azim_deg=0.0, elev_deg=0.0, W=1600, H=1100, bg=(13, 14, 20), ss=2):
    W, H = W * ss, H * ss
    keep = alpha > 0.42
    xyz, rgb, alpha = xyz[keep], rgb[keep], alpha[keep]

    c = np.median(xyz, axis=0)
    p = xyz - c
    # PCA: two largest axes span the picture plane, smallest is the view axis
    _, _, vt = np.linalg.svd(p - p.mean(0), full_matrices=False)
    right, up, view = vt[0], vt[1], vt[2]
    up = np.array([0, 0, 1.0])  # header says vertical axis is z
    up = up - view * (up @ view)
    up /= np.linalg.norm(up)
    right = np.cross(up, view); right /= np.linalg.norm(right)

    # optional orbit around the up axis / tilt
    az, el = np.radians(azim_deg), np.radians(elev_deg)
    view = view * np.cos(az) + right * np.sin(az)
    right = np.cross(up, view); right /= np.linalg.norm(right)
    view = view * np.cos(el) + up * np.sin(el)
    up = np.cross(view, right); up /= np.linalg.norm(up)

    u = p @ right
    v = p @ up
    d = p @ view

    # cull far floaters by depth, then frame on the DENSE subject via alpha-weighted
    # centroid + spread (ignores sparse outliers that otherwise shrink the subject)
    dlo, dhi = np.percentile(d, 6), np.percentile(d, 82)
    band = (d >= dlo) & (d <= dhi)
    u, v, d, rgb, alpha = u[band], v[band], d[band], rgb[band], alpha[band]
    w0 = alpha
    # robust center: start at weighted mean, refine within 1.5x spread (twice)
    uc = np.average(u, weights=w0); vc = np.average(v, weights=w0)
    for _ in range(2):
        su = np.sqrt(np.average((u - uc) ** 2, weights=w0))
        sv = np.sqrt(np.average((v - vc) ** 2, weights=w0))
        near = ((u - uc) ** 2 / (1.6 * su) ** 2 + (v - vc) ** 2 / (1.6 * sv) ** 2) < 1
        uc = np.average(u[near], weights=w0[near]); vc = np.average(v[near], weights=w0[near])
    half = 1.7 * max(su, sv * H / W)  # square-ish framing in world units
    u0, u1 = uc - half * (W / H), uc + half * (W / H)
    v0, v1 = vc - half, vc + half
    scale = min((W - 1) / (u1 - u0), (H - 1) / (v1 - v0))
    px = ((u - u0) * scale).astype(np.int64)
    py = (H - 1 - (v - v0) * scale).astype(np.int64)

    inb = (px >= 1) & (px < W - 1) & (py >= 1) & (py < H - 1)
    px, py, rgb, alpha, d = px[inb], py[inb], rgb[inb], alpha[inb], d[inb]

    # depth bias: nearer points weigh more (soft occlusion approximation)
    dn = (d - d.min()) / (np.ptp(d) + 1e-9)
    w = alpha * np.exp(-1.4 * dn)

    acc = np.zeros((H, W, 3))
    wsum = np.zeros((H, W))
    # 3x3 gaussian footprint for anti-aliasing
    for dx, dy, gw in [(0,0,1.0),(1,0,.5),(-1,0,.5),(0,1,.5),(0,-1,.5),
                        (1,1,.25),(1,-1,.25),(-1,1,.25),(-1,-1,.25)]:
        ww = w * gw
        np.add.at(acc, (py + dy, px + dx), rgb * ww[:, None])
        np.add.at(wsum, (py + dy, px + dx), ww)

    cov = wsum / (np.percentile(wsum[wsum > 0], 92) + 1e-9)  # coverage -> alpha over bg
    cov = np.clip(cov, 0, 1)[:, :, None]
    color = np.divide(acc, wsum[:, :, None], out=np.zeros_like(acc), where=wsum[:, :, None] > 0)
    color = np.clip(color * 1.4, 0, 1) ** 0.72  # lift + gamma
    img = color * cov + (np.array(bg) / 255.0) * (1 - cov)

    # mass-based auto-crop: center on the bright subject, drop dead space + far specks
    bg_lum = np.array(bg).mean() / 255.0
    sig = np.clip(img.mean(2) - bg_lum, 0, None)
    sig = np.where(sig > sig.max() * 0.10, sig, 0)  # ignore faint haze
    def span(mass, frac=0.25):
        idx = np.where(mass > mass.max() * frac)[0]  # strong band only
        return int(idx.min()), int(idx.max())
    x0, x1 = span(sig.sum(0)); y0, y1 = span(sig.sum(1))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    pad = 1.18
    halfw = (x1 - x0) / 2 * pad; halfh = (y1 - y0) / 2 * pad
    aspect = W / H  # keep target 3:2-ish aspect, centered on subject
    if halfw / halfh < aspect:
        halfw = halfh * aspect
    else:
        halfh = halfw / aspect
    cx = min(max(cx, halfw), W - halfw); cy = min(max(cy, halfh), H - halfh)
    cropped = img[int(cy - halfh):int(cy + halfh), int(cx - halfw):int(cx + halfw)]
    out = Image.fromarray((np.clip(cropped, 0, 1) * 255).astype(np.uint8))
    fw = 1760
    out = out.resize((fw, int(fw * out.height / out.width)), Image.LANCZOS)
    return out


if __name__ == "__main__":
    xyz, rgb, alpha = load(PLY)
    print(f"loaded {len(xyz)} gaussians")
    for name, az, el in [("a", 25, 8), ("b", 15, 5)]:
        render(xyz, rgb, alpha, az, el).save(f"assets/nerf_splat_{name}.png")
        print("wrote", f"assets/nerf_splat_{name}.png")
