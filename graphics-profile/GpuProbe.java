import android.opengl.*;
import java.nio.ByteBuffer;

public class GpuProbe {
    public static void main(String[] args) {
        EGLDisplay display=EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
        EGLContext context=EGL14.EGL_NO_CONTEXT;
        EGLSurface surface=EGL14.EGL_NO_SURFACE;
        try {
            if(!EGL14.eglInitialize(display,new int[2],0,new int[2],0)) throw new RuntimeException("eglInitialize");
            EGLConfig[] configs=new EGLConfig[1]; int[] count=new int[1];
            int[] attributes={EGL14.EGL_RENDERABLE_TYPE,EGL14.EGL_OPENGL_ES2_BIT,EGL14.EGL_SURFACE_TYPE,EGL14.EGL_PBUFFER_BIT,
                EGL14.EGL_RED_SIZE,8,EGL14.EGL_GREEN_SIZE,8,EGL14.EGL_BLUE_SIZE,8,EGL14.EGL_ALPHA_SIZE,8,EGL14.EGL_NONE};
            if(!EGL14.eglChooseConfig(display,attributes,0,configs,0,1,count,0)||count[0]==0) throw new RuntimeException("eglChooseConfig");
            context=EGL14.eglCreateContext(display,configs[0],EGL14.EGL_NO_CONTEXT,new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,2,EGL14.EGL_NONE},0);
            surface=EGL14.eglCreatePbufferSurface(display,configs[0],new int[]{EGL14.EGL_WIDTH,1,EGL14.EGL_HEIGHT,1,EGL14.EGL_NONE},0);
            if(!EGL14.eglMakeCurrent(display,surface,surface,context)) throw new RuntimeException("eglMakeCurrent");
            System.out.println("VENDOR="+GLES20.glGetString(GLES20.GL_VENDOR));
            System.out.println("RENDERER="+GLES20.glGetString(GLES20.GL_RENDERER));
            System.out.println("VERSION="+GLES20.glGetString(GLES20.GL_VERSION));
            GLES20.glDisable(GLES20.GL_DITHER);
            GLES20.glClearColor(.25f,.5f,.75f,1f); GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
            ByteBuffer pixel=ByteBuffer.allocateDirect(4);
            GLES20.glReadPixels(0,0,1,1,GLES20.GL_RGBA,GLES20.GL_UNSIGNED_BYTE,pixel);
            int error=GLES20.glGetError();
            int red=pixel.get(0)&255,green=pixel.get(1)&255,blue=pixel.get(2)&255;
            System.out.println("PIXEL="+red+","+green+","+blue+" GL_ERROR="+error);
            if(error!=0||Math.abs(red-64)>1||Math.abs(green-128)>1||Math.abs(blue-191)>1) throw new RuntimeException("Pixel read-back mismatch");
            System.out.println("GPU_DRAW_OK");
        } finally {
            EGL14.eglMakeCurrent(display,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_CONTEXT);
            if(surface!=EGL14.EGL_NO_SURFACE) EGL14.eglDestroySurface(display,surface);
            if(context!=EGL14.EGL_NO_CONTEXT) EGL14.eglDestroyContext(display,context);
            EGL14.eglTerminate(display);
        }
    }
}
