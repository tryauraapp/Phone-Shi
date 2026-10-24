package ai.phoneshi.cameraprobe;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.SystemClock;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.ImageFormat;
import android.graphics.Matrix;
import android.graphics.Rect;
import android.graphics.YuvImage;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CaptureRequest;
import android.media.Image;
import android.media.ImageReader;
import android.view.WindowManager;
import android.view.Surface;
import android.view.TextureView;
import android.graphics.SurfaceTexture;
import android.view.Gravity;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.FrameLayout;
import android.util.Range;
import java.io.FileOutputStream;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.security.MessageDigest;
import java.util.Collections;
import java.util.HashSet;

/** Reads the public front Camera2 API; never supplies or replaces camera data. */
public class CameraProbe extends Activity {
    private CameraDevice camera;
    private ImageReader reader;
    private HandlerThread thread;
    private Handler handler;
    private TextView status;
    private ImageView preview;
    private TextureView texture;
    private Surface previewSurface;
    private boolean textureMode;
    private int textureUpdates;
    private FileOutputStream log;
    private int frames;
    private volatile boolean closing;
    private volatile int generation;
    private long lastPreviewMs;
    private long sampleStartedMs, sampleDurationMs, lastRecordMs;
    private final HashSet<String> hashes = new HashSet<>();

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.BLACK);
        status = new TextView(this);
        status.setTextColor(Color.WHITE);
        status.setTextSize(12);
        status.setPadding(16, 8, 16, 8);
        status.setText("Opening front Camera2 feed...");
        preview = new ImageView(this);
        preview.setScaleType(ImageView.ScaleType.FIT_XY);
        preview.setContentDescription("Front camera preview, aspect 3:4");
        // "texture" mode previews through a SurfaceTexture, the same consumer path
        // as the stock Camera and CameraX PreviewView; the default reads YUV frames.
        textureMode = "texture".equals(getIntent().getStringExtra("mode"));
        texture = new TextureView(this);
        final android.view.View shown = textureMode ? texture : preview;
        final FrameLayout stage = new FrameLayout(this);
        stage.addView(shown, new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER));
        stage.addOnLayoutChangeListener((view, left, top, right, bottom, oldLeft, oldTop, oldRight, oldBottom) -> {
            int width = Math.min(stage.getWidth(), stage.getHeight() * 3 / 4);
            if (width > 0) shown.setLayoutParams(new FrameLayout.LayoutParams(width, width * 4 / 3, Gravity.CENTER));
        });
        root.addView(status);
        root.addView(stage, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
    }

    @Override public void onResume() {
        super.onResume();
        closing = false;
        final int attempt = ++generation;
        frames = 0;
        hashes.clear();
        lastPreviewMs = 0;
        sampleStartedMs = SystemClock.elapsedRealtime();
        sampleDurationMs = Math.min(600000L, Math.max(5000L, getIntent().getLongExtra("sample_ms", 22000L)));
        lastRecordMs = 0;
        textureUpdates = 0;
        thread = new HandlerThread("CameraFeedProbe");
        thread.start();
        handler = new Handler(thread.getLooper());
        if (textureMode) {
            texture.setSurfaceTextureListener(new TextureView.SurfaceTextureListener() {
                @Override public void onSurfaceTextureAvailable(SurfaceTexture st, int w, int h) { openFeed(attempt, st); }
                @Override public void onSurfaceTextureSizeChanged(SurfaceTexture st, int w, int h) {}
                @Override public boolean onSurfaceTextureDestroyed(SurfaceTexture st) { return true; }
                @Override public void onSurfaceTextureUpdated(SurfaceTexture st) { textureUpdates++; }
            });
            if (texture.isAvailable()) openFeed(attempt, texture.getSurfaceTexture());
            return;
        }
        openFeed(attempt, null);
    }

    private void sampleTexture(int attempt) {
        if (closing || generation != attempt) return;
        try {
            Bitmap bitmap = texture.getBitmap(128, 96);
            if (bitmap != null) {
                int[] pixels = new int[128 * 96];
                bitmap.getPixels(pixels, 0, 128, 0, 0, 128, 96);
                byte[] luma = new byte[128 * 96];
                for (int i = 0; i < pixels.length; i++) {
                    int c = pixels[i];
                    luma[i] = (byte)((Color.red(c) * 299 + Color.green(c) * 587 + Color.blue(c) * 114) / 1000);
                }
                record(luma, SystemClock.elapsedRealtimeNanos(), attempt,
                       "SurfaceTexture preview · updates " + textureUpdates);
            }
        } catch (Exception error) { fail(error.toString()); }
        handler.postDelayed(() -> sampleTexture(attempt), 200);
    }

    private void openFeed(final int attempt, SurfaceTexture surfaceTexture) {
        try {
            log = openFileOutput("frames.jsonl", MODE_PRIVATE);
            CameraManager manager = (CameraManager)getSystemService(CAMERA_SERVICE);
            String front = null;
            for (String id : manager.getCameraIdList()) {
                Integer facing = manager.getCameraCharacteristics(id).get(CameraCharacteristics.LENS_FACING);
                if (facing != null && facing == CameraCharacteristics.LENS_FACING_FRONT) front = id;
            }
            if (front == null) throw new Exception("No front camera exposed by Android");
            int captureWidth = getIntent().getIntExtra("capture_width", 640);
            int captureHeight = getIntent().getIntExtra("capture_height", 480);
            final Surface target;
            if (textureMode) {
                surfaceTexture.setDefaultBufferSize(captureWidth, captureHeight);
                previewSurface = new Surface(surfaceTexture);
                target = previewSurface;
                handler.postDelayed(() -> sampleTexture(attempt), 500);
            } else {
                reader = ImageReader.newInstance(captureWidth, captureHeight, ImageFormat.YUV_420_888, 3);
                reader.setOnImageAvailableListener(this::onImage, handler);
                target = reader.getSurface();
            }
            manager.openCamera(front, new CameraDevice.StateCallback() {
                @Override public void onOpened(CameraDevice device) {
                    if (closing || generation != attempt) { device.close(); return; }
                    camera = device;
                    try {
                        camera.createCaptureSession(Collections.singletonList(target),
                            new CameraCaptureSession.StateCallback() {
                                @Override public void onConfigured(CameraCaptureSession session) {
                                    if (closing || camera == null || generation != attempt) { session.close(); return; }
                                    try {
                                        CaptureRequest.Builder request = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                                        request.addTarget(target);
                                        request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, new Range<Integer>(30, 30));
                                        request.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_OFF);
                                        session.setRepeatingRequest(request.build(), null, handler);
                                    } catch (Exception error) { fail(error.toString()); }
                                }
                                @Override public void onConfigureFailed(CameraCaptureSession session) { fail("Session configuration failed"); }
                            }, handler);
                    } catch (Exception error) { fail(error.toString()); }
                }
                @Override public void onDisconnected(CameraDevice device) { device.close(); fail("Camera disconnected"); }
                @Override public void onError(CameraDevice device, int error) { device.close(); fail("Camera error " + error); }
            }, handler);
        } catch (Exception error) { fail(error.toString()); }
    }

    private void onImage(ImageReader source) {
        Image image = null;
        final int frameGeneration = generation;
        try {
            if (source != reader) return;
            image = source.acquireLatestImage();
            if (image == null || closing) return;
            Image.Plane[] planes = image.getPlanes();
            final int sourceWidth = image.getWidth(), sourceHeight = image.getHeight();
            ByteBuffer yyData = planes[0].getBuffer(), uData = planes[1].getBuffer(), vData = planes[2].getBuffer();
            int ys = planes[0].getRowStride(), yp = planes[0].getPixelStride();
            int us = planes[1].getRowStride(), up = planes[1].getPixelStride();
            int vs = planes[2].getRowStride(), vp = planes[2].getPixelStride();
            byte[] luma = new byte[128 * 96];
            for (int y = 0; y < 96; y++) for (int x = 0; x < 128; x++) {
                int sx = x * sourceWidth / 128, sy = y * sourceHeight / 96;
                luma[y * 128 + x] = yyData.get(sy * ys + sx * yp);
            }
            if (!record(luma, image.getTimestamp(), frameGeneration, null)) return;
            if (SystemClock.elapsedRealtime() - lastPreviewMs < 100) return;
            lastPreviewMs = SystemClock.elapsedRealtime();
            // Bulk plane copies plus Android's native YUV conversion avoid
            // hundreds of thousands of interpreted per-pixel buffer calls.
            byte[] nv21 = new byte[sourceWidth * sourceHeight * 3 / 2];
            byte[] yRow = new byte[(sourceWidth - 1) * yp + 1];
            for (int y = 0; y < sourceHeight; y++) {
                yyData.position(y * ys);
                if (yp == 1) yyData.get(nv21, y * sourceWidth, sourceWidth);
                else {
                    yyData.get(yRow);
                    for (int x = 0; x < sourceWidth; x++) nv21[y * sourceWidth + x] = yRow[x * yp];
                }
            }
            int chromaWidth = sourceWidth / 2;
            byte[] uRow = new byte[(chromaWidth - 1) * up + 1];
            byte[] vRow = new byte[(chromaWidth - 1) * vp + 1];
            int offset = sourceWidth * sourceHeight;
            for (int y = 0; y < sourceHeight / 2; y++) {
                uData.position(y * us); uData.get(uRow);
                vData.position(y * vs); vData.get(vRow);
                for (int x = 0; x < chromaWidth; x++) {
                    nv21[offset++] = vRow[x * vp];
                    nv21[offset++] = uRow[x * up];
                }
            }
            ByteArrayOutputStream jpeg = new ByteArrayOutputStream();
            new YuvImage(nv21, ImageFormat.NV21, sourceWidth, sourceHeight, null)
                .compressToJpeg(new Rect(0, 0, sourceWidth, sourceHeight), 92, jpeg);
            byte[] encoded = jpeg.toByteArray();
            Bitmap bitmap = BitmapFactory.decodeByteArray(encoded, 0, encoded.length);
            Matrix rotation = new Matrix();
            rotation.postRotate(90);
            rotation.postScale(-1, 1);
            Bitmap upright = Bitmap.createBitmap(bitmap, 0, 0, sourceWidth, sourceHeight, rotation, false);
            final String text = "Front Camera2 · frames " + frames + " · distinct pixel samples " + hashes.size();
            runOnUiThread(() -> { if (!closing && generation == frameGeneration) { status.setText(text); preview.setImageBitmap(upright); } });
        } catch (Exception error) { if (generation == frameGeneration) fail(error.toString()); }
        finally { if (image != null) image.close(); }
    }

    /** Hash one 128x96 luma sample, log it, and keep first/latest evidence frames. */
    private synchronized boolean record(byte[] luma, long timestampNs, int attempt, String label) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(luma);
        StringBuilder hash = new StringBuilder();
        final String hex = "0123456789abcdef";
        for (byte value : digest) { hash.append(hex.charAt((value & 255) >> 4)); hash.append(hex.charAt(value & 15)); }
        if (hashes.size() < 1000) hashes.add(hash.toString());
        frames++;
        if (closing || generation != attempt || log == null) return false;
        long nowMs = SystemClock.elapsedRealtime();
        String row = "{\"frame\":"+frames+",\"timestamp_ns\":"+timestampNs+",\"captured_elapsed_ns\":"+SystemClock.elapsedRealtimeNanos()
            +",\"consumer_updates\":"+textureUpdates+",\"sha256\":\""+hash+"\"}\n";
        if (nowMs - sampleStartedMs <= sampleDurationMs + 1000 && nowMs - lastRecordMs >= 200) {
            log.write(row.getBytes("UTF-8")); lastRecordMs = nowMs;
            FileOutputStream latest = openFileOutput("latest.tmp.pgm", MODE_PRIVATE);
            latest.write("P5\n128 96\n255\n".getBytes("US-ASCII")); latest.write(luma); latest.close();
            new java.io.File(getFilesDir(), "latest.tmp.pgm").renameTo(new java.io.File(getFilesDir(), "latest.pgm"));
        }
        if (frames == 1 || frames == 11) {
            FileOutputStream pgm = openFileOutput("frame-"+frames+".pgm", MODE_PRIVATE);
            pgm.write("P5\n128 96\n255\n".getBytes("US-ASCII"));
            pgm.write(luma);
            pgm.close();
        }
        if (label != null) {
            final String text = label + " · samples " + frames + " · distinct " + hashes.size();
            runOnUiThread(() -> { if (!closing && generation == attempt) status.setText(text); });
        }
        return true;
    }

    private void fail(String message) { if (!closing) runOnUiThread(() -> status.setText("ERROR: " + message)); }
    @Override public void onPause() {
        closing = true;
        generation++;
        if (camera != null) { camera.close(); camera = null; }
        if (reader != null) { reader.setOnImageAvailableListener(null, null); reader.close(); reader = null; }
        if (previewSurface != null) { previewSurface.release(); previewSurface = null; }
        if (thread != null) { thread.quitSafely(); thread = null; }
        try { if (log != null) { log.close(); log = null; } } catch (Exception ignored) {}
        super.onPause();
    }
}
