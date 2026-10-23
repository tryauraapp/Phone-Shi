package dev.emulab.devicecheck;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageInfo;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.hardware.Sensor;
import android.hardware.SensorManager;
import android.net.ConnectivityManager;
import android.net.LinkAddress;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.telephony.TelephonyManager;
import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLSurface;
import android.opengl.GLES20;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.InputStreamReader;
import java.text.DateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;

public class MainActivity extends Activity {
    private static final int BG = Color.rgb(15, 19, 27), CARD = Color.rgb(25, 31, 42);
    private static final int TEXT = Color.rgb(239, 242, 247), MUTED = Color.rgb(161, 174, 195);
    private static final int RED = Color.rgb(255, 124, 133), AMBER = Color.rgb(255, 192, 118), GREEN = Color.rgb(123, 213, 172);
    private final Handler handler = new Handler(Looper.getMainLooper());
    private LinearLayout findings;
    private TextView summary, subtitle;
    private Button scanButton;
    private volatile String report = "Scan has not completed.";
    private int generation = 0;

    private static class Finding {
        final String name, evidence, meaning;
        final int severity; // 2=flag, 1=weak indicator, 0=not observed, -1=unknown, -2=context
        Finding(String name, int severity, String evidence, String meaning) {
            this.name=name; this.severity=severity; this.evidence=evidence; this.meaning=meaning;
        }
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(BG); getWindow().setNavigationBarColor(BG);
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setBackgroundColor(BG);
        // Respect status/navigation bars when targeting Android 15 edge-to-edge.
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(dp(20), insets.getSystemWindowInsetTop()+dp(14), dp(20), insets.getSystemWindowInsetBottom()+dp(8));
            return insets;
        });
        root.setPadding(dp(20),dp(24),dp(20),dp(12));
        TextView eyebrow = text("EMU LAB  /  LOCAL DEVICE CHECK", 11, AMBER); eyebrow.setLetterSpacing(.12f); root.addView(eyebrow);
        TextView title = text("Device red flags", 29, TEXT); title.setTypeface(Typeface.DEFAULT,Typeface.BOLD); root.addView(title);
        subtitle = text("Public Android heuristics • no root requested", 13, MUTED); root.addView(subtitle);
        summary = text("Preparing scan…", 21, TEXT); summary.setPadding(0,dp(20),0,dp(10)); root.addView(summary);
        LinearLayout buttons = new LinearLayout(this);
        scanButton = new Button(this); scanButton.setText("Scan again"); scanButton.setAllCaps(false);
        scanButton.setOnClickListener(v -> scan()); buttons.addView(scanButton,new LinearLayout.LayoutParams(0,dp(50),1));
        Button copy = new Button(this); copy.setText("Copy report"); copy.setAllCaps(false);
        copy.setOnClickListener(v -> {
            ((ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText("Device diagnostic",report));
            Toast.makeText(this,"Report copied",Toast.LENGTH_SHORT).show();
        }); buttons.addView(copy,new LinearLayout.LayoutParams(0,dp(50),1)); root.addView(buttons);
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true);
        findings = new LinearLayout(this); findings.setOrientation(LinearLayout.VERTICAL); findings.setPadding(0,dp(12),0,0);
        scroll.addView(findings); root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        setContentView(root); root.requestApplyInsets(); scan();
    }

    private int dp(int value) { return (int)(value*getResources().getDisplayMetrics().density+.5f); }
    private TextView text(String value, int size, int color) {
        TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(color);
        view.setLineSpacing(dp(3),1); view.setTextIsSelectable(true); return view;
    }
    private String label(int severity) {
        return severity==2 ? "RED FLAG" : severity==1 ? "WEAK SIGNAL" : severity==0 ? "NOT OBSERVED" : severity==-1 ? "NOT TESTED / UNKNOWN" : "CONTEXT";
    }
    private void showFinding(Finding item) {
        int color = item.severity==2 ? RED : item.severity==1 ? AMBER : item.severity==0 ? GREEN : MUTED;
        LinearLayout card = new LinearLayout(this); card.setOrientation(LinearLayout.VERTICAL); card.setPadding(dp(16),dp(14),dp(16),dp(14));
        GradientDrawable background = new GradientDrawable(); background.setColor(CARD); background.setCornerRadius(dp(14)); card.setBackground(background);
        TextView badge=text(label(item.severity),10,color); badge.setLetterSpacing(.1f); card.addView(badge);
        TextView name=text(item.name,17,TEXT); name.setTypeface(Typeface.DEFAULT,Typeface.BOLD); name.setPadding(0,dp(5),0,dp(6)); card.addView(name);
        TextView evidence=text(item.evidence,12,color); evidence.setTypeface(Typeface.MONOSPACE); card.addView(evidence);
        TextView explanation=text(item.meaning,12,MUTED); explanation.setPadding(0,dp(8),0,0); card.addView(explanation);
        LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(-1,-2); layout.bottomMargin=dp(10); findings.addView(card,layout);
    }

    private void scan() {
        final int current=++generation; scanButton.setEnabled(false); summary.setText("Inspecting app-visible signals…"); findings.removeAllViews();
        new Thread(() -> {
            List<Finding> rows = new ArrayList<>();
            try { collect(rows); }
            catch (Exception error) { rows.add(new Finding("Incomplete scan",-1,error.toString(),"Some checks could not complete. Missing data is not a pass.")); }
            rows.sort((a,b) -> Integer.compare(b.severity,a.severity));
            StringBuilder plain = new StringBuilder("Device Red Flags — "+new Date()+"\nHeuristic checker; not Bumble's proprietary detector.\n\n");
            JSONArray jsonRows=new JSONArray(); int flags=0, weak=0;
            for (Finding row:rows) {
                if(row.severity==2) flags++; if(row.severity==1) weak++;
                plain.append(label(row.severity)).append(" | ").append(row.name).append("\n").append(row.evidence).append("\n").append(row.meaning).append("\n\n");
                try { JSONObject object=new JSONObject(); object.put("name",row.name); object.put("severity",label(row.severity)); object.put("evidence",row.evidence); object.put("meaning",row.meaning); jsonRows.put(object); } catch(Exception ignored) {}
            }
            report=plain.toString();
            try {
                JSONObject export=new JSONObject(); export.put("checkedAt",new Date().toString()); export.put("redFlags",flags); export.put("weakSignals",weak); export.put("findings",jsonRows);
                // App-specific external storage; readable over ADB for lab verification.
                File directory=getExternalFilesDir(null);
                if(directory!=null) try(java.io.FileWriter writer=new java.io.FileWriter(new File(directory,"latest-report.json"))) { writer.write(export.toString(2)); }
            } catch(Exception ignored) {}
            final int redCount=flags, weakCount=weak;
            runOnUiThread(() -> {
                if(isFinishing() || generation!=current) return;
                summary.setText(redCount+" red flags · "+weakCount+" weak signals"); summary.setTextColor(redCount>0?RED:TEXT);
                subtitle.setText(Build.MODEL+" · Android "+Build.VERSION.RELEASE+" · ordinary app sandbox");
                for(Finding row:rows) showFinding(row); scanButton.setEnabled(true);
                sampleBattery(current);
            });
        },"device-scan").start();
    }

    private void collect(List<Finding> out) throws Exception {
        out.add(new Finding("What this checker can establish",-2,"Runs under its own Android app UID. No su request, no network permission.","Public local checks, not a copy of Bumble. Magisk isolation is per app: this app can see different mounts from Bumble unless given matching DenyList entries. No acceptance or ban prediction is possible."));
        String hardware=Build.HARDWARE, props=getProperties();
        out.add(new Finding("Emulator hardware",emulatorWord(hardware)?2:0,"Build.HARDWARE="+hardware,"ranchu and goldfish identify Android Emulator hardware. A phone-like model name does not change this value."));
        String qemu=prop(props,"ro.kernel.qemu"), bootQemu=prop(props,"ro.boot.qemu");
        int qemuSeverity="1".equals(qemu)||"1".equals(bootQemu)?2:(qemu.isEmpty()&&bootQemu.isEmpty()?-1:0);
        out.add(new Finding("QEMU properties",qemuSeverity,"ro.kernel.qemu="+unknown(qemu)+"\nro.boot.qemu="+unknown(bootQemu),"Read with getprop as this app's UID. Blank or restricted properties are unknown, not evidence of a physical device."));
        String fp=Build.FINGERPRINT;
        boolean synthetic=fp.contains("TEST.S25")||fp.contains("123456:user");
        out.add(new Finding("Build fingerprint",emulatorWord(fp)||synthetic?2:0,fp,synthetic?"The fingerprint contains the explicit lab fixture markers TEST.S25 / 123456. This is evidence of a synthetic profile.":"Checks common emulator and lab markers only. A plausible string does not authenticate a device."));
        String[] segments=fp.split("/"); boolean mismatch=false;
        if(segments.length>=5) mismatch=!segments[3].equals(Build.ID)||!segments[4].split(":")[0].equals(Build.VERSION.INCREMENTAL);
        out.add(new Finding("Build field consistency",mismatch?2:0,"ID="+Build.ID+"\nINCREMENTAL="+Build.VERSION.INCREMENTAL+"\nMODEL="+Build.MODEL+" / PRODUCT="+Build.PRODUCT,"Compares fingerprint ID and incremental against Build fields. A mismatch indicates inconsistent metadata; it does not uniquely identify an emulator."));
        List<String> paths=new ArrayList<>();
        for(String path:new String[]{"/dev/qemu_pipe","/dev/goldfish_pipe","/dev/socket/qemud","/dev/goldfish_address_space","/dev/goldfish_sync","/vendor/etc/init/hw/init.ranchu.rc","/vendor/etc/fstab.ranchu"}) if(new File(path).exists()) paths.add(path);
        out.add(new Finding("Emulator files",paths.isEmpty()?0:2,paths.isEmpty()?"No tested emulator paths visible":join(paths),"File existence is checked inside this app's mount namespace. SELinux can hide paths; absence does not prove stock hardware."));
        List<String> roots=new ArrayList<>();
        for(String path:new String[]{"/system_ext/bin/su","/system/bin/su","/system/xbin/su","/sbin/su","/debug_ramdisk/magisk"}) if(new File(path).exists()) roots.add(path);
        out.add(new Finding("Root binaries",roots.isEmpty()?0:2,roots.isEmpty()?"No tested su / Magisk binary visible":join(roots),"Checks file visibility only. The checker never executes su or asks for superuser. A DenyList can remove these mounts while root stays installed."));
        List<String> managers=new ArrayList<>();
        for(String pkg:new String[]{"com.topjohnwu.magisk","eu.chainfire.supersu"}) try { getPackageManager().getPackageInfo(pkg,0); managers.add(pkg); } catch(android.content.pm.PackageManager.NameNotFoundException ignored) {}
        out.add(new Finding("Root-manager packages",managers.isEmpty()?0:1,managers.isEmpty()?"No declared root-manager package visible":join(managers),"Manifest queries explicitly allow these two package lookups. A manager's installation is a weak indicator; unmounting su does not hide the manager package."));
        String boot=prop(props,"ro.boot.verifiedbootstate"),locked=prop(props,"ro.boot.flash.locked");
        out.add(new Finding("Reported boot state","orange".equals(boot)||"0".equals(locked)?2:(boot.isEmpty()&&locked.isEmpty()?-1:-2),"verifiedbootstate="+unknown(boot)+"\nflash.locked="+unknown(locked),"Local property strings are not cryptographic attestation. An empty value is unknown; a claimed green state is not independently verified."));
        out.add(new Finding("Build signing tags",Build.TAGS.contains("test-keys")?1:0,"TAGS="+Build.TAGS+" / TYPE="+Build.TYPE,"test-keys suggests custom firmware. release-keys alone does not prove a certified image."));
        SensorManager sensors=(SensorManager)getSystemService(SENSOR_SERVICE); List<String> virtualSensors=new ArrayList<>();
        List<Sensor> all=sensors.getSensorList(Sensor.TYPE_ALL);
        for(Sensor sensor:all) if(emulatorWord(sensor.getName()+" "+sensor.getVendor())) virtualSensors.add(sensor.getName()+" / "+sensor.getVendor());
        out.add(new Finding("Virtual sensor names",virtualSensors.isEmpty()?0:2,"Sensors: "+all.size()+"\n"+(virtualSensors.isEmpty()?"No tested virtual sensor names":join(virtualSensors)),"Names containing Goldfish, ranchu or an emulator marker expose virtual hardware. Sensor count alone is not scored."));
        String gpu=renderer();
        out.add(new Finding("Graphics renderer",emulatorWord(gpu)||gpu.toLowerCase(Locale.ROOT).contains("swiftshader")?2:(gpu.startsWith("Unavailable")?-1:0),gpu,"An app-created EGL context reads its actual OpenGL renderer. Emulator translators and SwiftShader are useful signals; this does not inspect another app."));
        try {
            ConnectivityManager connectivity=(ConnectivityManager)getSystemService(CONNECTIVITY_SERVICE);
            Network network=connectivity.getActiveNetwork(); LinkProperties links=network==null?null:connectivity.getLinkProperties(network);
            NetworkCapabilities caps=network==null?null:connectivity.getNetworkCapabilities(network);
            String transport=caps==null?"NONE":caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)?"CELLULAR":caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)?"WIFI":"OTHER";
            String radio="Unavailable";
            try { TelephonyManager phone=(TelephonyManager)getSystemService(TELEPHONY_SERVICE); int type=phone.getDataNetworkType(); radio=type==TelephonyManager.NETWORK_TYPE_LTE?"LTE":String.valueOf(type); } catch(SecurityException denied) { radio="Permission required"; }
            List<String> addresses=new ArrayList<>(); boolean typical=false;
            if(links!=null) for(LinkAddress address:links.getLinkAddresses()) { String value=address.getAddress().getHostAddress(); addresses.add(value); if(value.startsWith("10.0.2.")) typical=true; }
            out.add(new Finding("Network topology",typical?1:-2,"Transport="+transport+"\nData network="+radio+"\n"+(addresses.isEmpty()?"No active network addresses":join(addresses)),"Transport and radio type are read through Android APIs. 10.0.2.x is common on Android Emulator, but physical devices and VPNs can use the same subnet. No request is sent to a server."));
        } catch(Exception error) { out.add(new Finding("Network topology",-1,error.getClass().getSimpleName(),"Network information was unavailable to this app.")); }
        String cpu=readFile("/proc/cpuinfo",24000),lowerCpu=cpu.toLowerCase(Locale.ROOT);
        out.add(new Finding("CPU context",lowerCpu.contains("0x61")&&Build.MANUFACTURER.equalsIgnoreCase("samsung")?1:-2,"ABI="+join(java.util.Arrays.asList(Build.SUPPORTED_ABIS))+"\n"+cpuExcerpt(cpu),"An Apple implementer with a claimed Samsung model is inconsistent. CPU counts and missing /proc fields alone are not scored."));
        Intent battery=registerReceiver(null,new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        BatteryManager manager=(BatteryManager)getSystemService(BATTERY_SERVICE);
        out.add(new Finding("Battery snapshot",-2,batteryDescription(battery)+"\nCharge counter="+manager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CHARGE_COUNTER)+" µAh","Charge level is not battery wear. Android's GOOD health enum is not a 100% health measurement. One sample cannot establish degradation or prove emulation."));
        PackageInfo own=getPackageManager().getPackageInfo(getPackageName(),0);
        out.add(new Finding("Installation and build dates",-2,"This checker installed: "+DateFormat.getDateTimeInstance().format(new Date(own.firstInstallTime))+"\nOS compiled: "+DateFormat.getDateTimeInstance().format(new Date(Build.TIME))+"\nUptime: "+SystemClock.elapsedRealtime()/60000+" min","firstInstallTime belongs to one app, not the device's first-ever setup. Fresh installs and factory resets occur on real phones. No age-based red flag is assigned."));
        out.add(new Finding("Developer / ADB settings",-2,"ADB enabled="+Settings.Global.getInt(getContentResolver(),Settings.Global.ADB_ENABLED,0),"A development setting is not proof of root or emulation. It is shown as context only."));
        out.add(new Finding("Google Play Integrity",-1,"NOT REQUESTED — no Cloud/Play configuration or backend","A genuine integrity verdict is issued by Google for this app and request. This local checker cannot infer Bumble's verdict or mint one from device properties."));
        out.add(new Finding("Storage fragmentation / device age",-1,"NOT INFERRED","An ordinary app cannot reliably age a device from filesystem fragmentation. Its sandbox and filesystem behavior make a universal physical-device age test unreliable."));
    }

    private void sampleBattery(int current) {
        final String before=batteryDescription(registerReceiver(null,new IntentFilter(Intent.ACTION_BATTERY_CHANGED)));
        TextView sampling=text("Battery comparison: sampling again in 12 seconds…",12,MUTED); findings.addView(sampling);
        handler.postDelayed(() -> {
            if(isFinishing()||generation!=current) return;
            String after=batteryDescription(registerReceiver(null,new IntentFilter(Intent.ACTION_BATTERY_CHANGED)));
            sampling.setText("Battery, 12-second comparison\n"+after+"\n"+(before.equals(after)?"Values stayed constant. Normal over a short interval; not scored.":"At least one sampled field changed; not proof of physical hardware."));
        },12000);
    }
    private String batteryDescription(Intent battery) {
        if(battery==null) return "Battery broadcast unavailable";
        return "level="+battery.getIntExtra(BatteryManager.EXTRA_LEVEL,-1)+"/"+battery.getIntExtra(BatteryManager.EXTRA_SCALE,-1)
            +" · temp="+(battery.getIntExtra(BatteryManager.EXTRA_TEMPERATURE,-1)/10.0)+" °C"
            +"\nvoltage="+battery.getIntExtra(BatteryManager.EXTRA_VOLTAGE,-1)+" mV · status="+battery.getIntExtra(BatteryManager.EXTRA_STATUS,-1)
            +" · health enum="+battery.getIntExtra(BatteryManager.EXTRA_HEALTH,-1);
    }
    private static boolean emulatorWord(String value) {
        String lower=value.toLowerCase(Locale.ROOT);
        for(String word:new String[]{"ranchu","goldfish","emulator","qemu","sdk_gphone","generic/sdk","genymotion","bluestacks","opengl es translator"}) if(lower.contains(word)) return true;
        return false;
    }
    private static String unknown(String value) { return value.isEmpty()?"<unavailable>":value; }
    private static String join(List<String> values) { StringBuilder text=new StringBuilder(); for(String value:values) { if(text.length()>0) text.append('\n'); text.append(value); } return text.toString(); }
    private String getProperties() throws Exception {
        Process process=new ProcessBuilder("/system/bin/getprop").redirectErrorStream(true).start();
        // Drain stdout before waiting: getprop output can exceed pipe capacity.
        Runnable timeout=() -> process.destroyForcibly(); handler.postDelayed(timeout,3000);
        StringBuilder result=new StringBuilder();
        try(BufferedReader reader=new BufferedReader(new InputStreamReader(process.getInputStream()))) { String line; while((line=reader.readLine())!=null) result.append(line).append('\n'); }
        finally { handler.removeCallbacks(timeout); }
        if(!process.waitFor(1,TimeUnit.SECONDS)) process.destroyForcibly();
        return result.toString();
    }
    private static String prop(String properties,String key) {
        String prefix="["+key+"]: [";
        for(String line:properties.split("\n")) if(line.startsWith(prefix)&&line.endsWith("]")) return line.substring(prefix.length(),line.length()-1);
        return "";
    }
    private static String readFile(String path,int limit) {
        StringBuilder result=new StringBuilder();
        try(BufferedReader reader=new BufferedReader(new FileReader(path))) { String line; while((line=reader.readLine())!=null&&result.length()<limit) result.append(line).append('\n'); }
        catch(Exception error) { return "Unavailable: "+error.getClass().getSimpleName(); }
        return result.toString();
    }
    private static String cpuExcerpt(String cpu) {
        List<String> lines=new ArrayList<>();
        for(String line:cpu.split("\n")) if(line.toLowerCase(Locale.ROOT).startsWith("cpu implementer")||line.toLowerCase(Locale.ROOT).startsWith("hardware")||line.startsWith("Unavailable")) if(!lines.contains(line)) lines.add(line);
        return lines.isEmpty()?"CPU implementer / hardware not exposed":join(lines);
    }
    private static String renderer() {
        EGLDisplay display=EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
        EGLContext context=EGL14.EGL_NO_CONTEXT; EGLSurface surface=EGL14.EGL_NO_SURFACE;
        try {
            if(!EGL14.eglInitialize(display,new int[2],0,new int[2],0)) return "Unavailable: EGL initialization failed";
            EGLConfig[] configs=new EGLConfig[1]; int[] count=new int[1];
            if(!EGL14.eglChooseConfig(display,new int[]{EGL14.EGL_RENDERABLE_TYPE,EGL14.EGL_OPENGL_ES2_BIT,EGL14.EGL_SURFACE_TYPE,EGL14.EGL_PBUFFER_BIT,EGL14.EGL_NONE},0,configs,0,1,count,0)||count[0]==0) return "Unavailable: no EGL config";
            context=EGL14.eglCreateContext(display,configs[0],EGL14.EGL_NO_CONTEXT,new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,2,EGL14.EGL_NONE},0);
            surface=EGL14.eglCreatePbufferSurface(display,configs[0],new int[]{EGL14.EGL_WIDTH,1,EGL14.EGL_HEIGHT,1,EGL14.EGL_NONE},0);
            if(!EGL14.eglMakeCurrent(display,surface,surface,context)) return "Unavailable: EGL context failed";
            return GLES20.glGetString(GLES20.GL_VENDOR)+"\n"+GLES20.glGetString(GLES20.GL_RENDERER);
        } catch(Exception error) { return "Unavailable: "+error.getClass().getSimpleName(); }
        finally {
            EGL14.eglMakeCurrent(display,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_CONTEXT);
            if(surface!=EGL14.EGL_NO_SURFACE) EGL14.eglDestroySurface(display,surface);
            if(context!=EGL14.EGL_NO_CONTEXT) EGL14.eglDestroyContext(display,context);
            EGL14.eglTerminate(display);
        }
    }
    @Override public void onDestroy() { generation++; handler.removeCallbacksAndMessages(null); super.onDestroy(); }
}
