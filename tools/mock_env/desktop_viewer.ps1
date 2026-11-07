param([string]$Config)
# 데스크톱 전자문서 뷰어 모의 프로그램 (종합 검증용)
#   onnara : 도구모음(본문복사·PC저장·인쇄) + 서식 있는 본문 + 붙임목록, PC저장 시 저장 대화상자
#   legacy : 옛 Win32 도구모음(ToolbarWindow32) + 일반 편집 칸, PC저장 시 정해진 폴더에 바로 저장
#   canvas : 글자 정보 없이 화면에 그림으로만 그리는 뷰어 (화면 글자 인식이 필요)
# 화면 밖(-20000,-20000)에 활성화 없이 띄워 사용자의 화면을 가리거나 포커스를 가져가지 않는다.
$ErrorActionPreference = 'Stop'
$cfg = Get-Content -Raw -Encoding UTF8 $Config | ConvertFrom-Json
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @"
using System; using System.Drawing; using System.IO; using System.Windows.Forms;
public class MockViewer : Form {
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
Set-Content -Path $cfg.ready_file -Value $form.Handle -Encoding ASCII
[System.Windows.Forms.Application]::Run($form)
