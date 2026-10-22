import android.os.Build;
public class BuildProbe {
  static void p(String k, String v){ System.out.println(k + "=" + v); }
  public static void main(String[] a){
    p("Build.MODEL", Build.MODEL); p("Build.MANUFACTURER", Build.MANUFACTURER);
    p("Build.BRAND", Build.BRAND); p("Build.DEVICE", Build.DEVICE);
    p("Build.PRODUCT", Build.PRODUCT); p("Build.BOARD", Build.BOARD);
    p("Build.HARDWARE", Build.HARDWARE); p("Build.FINGERPRINT", Build.FINGERPRINT);
    p("Build.DISPLAY", Build.DISPLAY); p("Build.ID", Build.ID); p("Build.TAGS", Build.TAGS);
    p("Build.TYPE", Build.TYPE); p("Build.HOST", Build.HOST); p("Build.USER", Build.USER);
    p("Build.BOOTLOADER", Build.BOOTLOADER); p("Build.SOC_MANUFACTURER", Build.SOC_MANUFACTURER);
    p("Build.SOC_MODEL", Build.SOC_MODEL); p("Build.SUPPORTED_ABIS", String.join(",", Build.SUPPORTED_ABIS));
    p("Build.VERSION.RELEASE", Build.VERSION.RELEASE); p("Build.VERSION.SDK_INT", ""+Build.VERSION.SDK_INT);
    p("Build.VERSION.INCREMENTAL", Build.VERSION.INCREMENTAL);
  }
}
