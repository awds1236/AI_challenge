param([string]$Config)
# 데스크톱 전자문서 뷰어 모의 프로그램 (종합 검증용)
#   onnara : 도구모음(본문복사·PC저장·인쇄) + 서식 있는 본문 + 붙임목록, PC저장 시 저장 대화상자
#   legacy : 옛 Win32 도구모음(ToolbarWindow32) + 일반 편집 칸, PC저장 시 정해진 폴더에 바로 저장
#   canvas : 글자 정보 없이 화면에 그림으로만 그리는 뷰어 (화면 글자 인식이 필요)
#   ── 뷰어가 아닌 일반 프로그램 (본문복사·PC저장 버튼, 붙임목록 없음) ──
#   generic  : 그림으로만 그리는 긴 업무 화면, 스크롤해야 끝까지 보인다 (화면 넘김 글자 인식)
#   docfile  : 제목에 '파일 [폴더] - 문서 편집기'만 있고 화면은 비어 있는 편집기 (열린 문서 파일 읽기)
#   owned    : 작업 표시줄용 크기 없는 껍데기 창 + 거기에 딸린 주 창 (옛 델파이 프로그램 구조)
#   minimized: 최소화된 채로 있는 그림 화면 프로그램
# 화면 밖(-20000,-20000)에 활성화 없이 띄워 사용자의 화면을 가리거나 포커스를 가져가지 않는다.
$ErrorActionPreference = 'Stop'
$cfg = Get-Content -Raw -Encoding UTF8 $Config | ConvertFrom-Json
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @"
using System; using System.Drawing; using System.IO; using System.Windows.Forms;
public class ShellWindow : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    public ShellWindow(string title) {
        Text = title; FormBorderStyle = FormBorderStyle.None; StartPosition = FormStartPosition.Manual;
        Location = new Point(-20000, -20000); Size = new Size(0, 0); ShowInTaskbar = true;
    }
}
public class MockViewer : Form {
    [System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams { get {
        CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000; /* WS_EX_NOACTIVATE */ return cp; } }
    string body; string[] lines;
    public MockViewer(string mode, string title, string body, string[] attach, string attachDir, string saveDir) {
        this.body = body; this.lines = body.Replace("\r", "").Split('\n');
        Text = title; StartPosition = FormStartPosition.Manual; Location = new Point(-20000, -20000);
        Size = new Size(1100, 760); Font = new Font("Malgun Gothic", 10f);
        if (mode == "onnara") {
            var ts = new ToolStrip();
            var copy = new ToolStripButton("본문복사"); copy.Click += (s, e) => Clipboard.SetText(this.body);
            var save = new ToolStripButton("PC저장");
            save.Click += (s, e) => {
                if (attach.Length == 0) return;
                var d = new SaveFileDialog(); d.FileName = attach[0]; d.InitialDirectory = saveDir;
                if (d.ShowDialog(this) == DialogResult.OK) File.Copy(Path.Combine(attachDir, attach[0]), d.FileName, true);
            };
            ts.Items.Add(copy); ts.Items.Add(save); ts.Items.Add(new ToolStripButton("인쇄"));
            var list = new ListBox(); list.Dock = DockStyle.Right; list.Width = 260; list.Items.Add("[붙임목록]");
            foreach (var a in attach) list.Items.Add(a);
            var rt = new RichTextBox(); rt.Dock = DockStyle.Fill; rt.ReadOnly = true; rt.Text = body;
            Controls.Add(rt); Controls.Add(list); Controls.Add(ts);
        } else if (mode == "legacy") {
            var tb = new ToolBar(); tb.Appearance = ToolBarAppearance.Flat; tb.TextAlign = ToolBarTextAlign.Right;
            tb.Buttons.Add(new ToolBarButton("본문복사")); tb.Buttons.Add(new ToolBarButton("PC저장"));
            tb.ButtonClick += (s, e) => {
                if (e.Button.Text == "본문복사") Clipboard.SetText(this.body);
                else foreach (var a in attach) File.Copy(Path.Combine(attachDir, a), Path.Combine(saveDir, a), true);
            };
            var box = new TextBox(); box.Multiline = true; box.ReadOnly = true; box.Dock = DockStyle.Fill;
            box.ScrollBars = ScrollBars.Vertical; box.Text = body.Replace("\n", "\r\n");
            Controls.Add(box); Controls.Add(tb);
        } else if (mode == "generic") {
            var outer = new Panel(); outer.Dock = DockStyle.Fill; outer.AutoScroll = true; outer.BackColor = Color.White;
            var inner = new Panel(); inner.Location = new Point(0, 0); inner.Size = new Size(1040, 80 + lines.Length * 100);
            inner.BackColor = Color.White;
            inner.Paint += (s, e) => {
                e.Graphics.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;
                using (var f = new Font("Malgun Gothic", 12.5f)) {
                    float y = 30; foreach (var l in lines) { e.Graphics.DrawString(l, f, Brushes.Black, 20, y); y += 100; }
                }
            };
            outer.Controls.Add(inner); Controls.Add(outer);
        } else if (mode == "docfile") {
            var panel = new Panel(); panel.Dock = DockStyle.Fill; panel.BackColor = Color.Gainsboro;
            Controls.Add(panel);
        } else if (mode == "owned") {
            var rt = new RichTextBox(); rt.Dock = DockStyle.Fill; rt.ReadOnly = true; rt.Text = body;
            Controls.Add(rt); ShowInTaskbar = false;
        } else {
            var panel = new Panel(); panel.Dock = DockStyle.Fill; panel.BackColor = Color.White;
            panel.Paint += (s, e) => {
                e.Graphics.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;
                using (var f = new Font("Malgun Gothic", 15f)) {
                    float y = 20; foreach (var l in lines) { e.Graphics.DrawString(l, f, Brushes.Black, 20, y); y += 34; }
                }
            };
            Controls.Add(panel);
        }
    }
}
"@
[System.Windows.Forms.Application]::EnableVisualStyles()
$body = Get-Content -Raw -Encoding UTF8 $cfg.body_file
[string[]]$attach = @($cfg.attach | Where-Object { $_ })
$form = New-Object MockViewer($cfg.mode, $cfg.title, $body, $attach, $cfg.attach_dir, $cfg.save_dir)
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = [int]$cfg.lifetime_ms; $timer.Add_Tick({ $form.Close() }); $timer.Start()
$ready = $form.Handle
if ($cfg.mode -eq "owned") {
    # 옛 델파이 프로그램: 작업 표시줄에는 크기 없는 껍데기 창만 있고, 실제 화면은 거기에 딸린 창이다
    $shell = New-Object ShellWindow($cfg.title)
    $shell.Show()
    $form.Owner = $shell
    $ready = $shell.Handle
}
$form.Add_Shown({
    # 사용자가 미리 최소화해 둔 창 (SW_SHOWMINNOACTIVE: 활성 창은 건드리지 않는다)
    if ($cfg.mode -eq "minimized") { [MockViewer]::ShowWindow($form.Handle, 7) | Out-Null }
    Set-Content -Path $cfg.ready_file -Value $ready -Encoding ASCII
})
[System.Windows.Forms.Application]::Run($form)
