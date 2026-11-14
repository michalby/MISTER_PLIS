// MISTER PLIS.app — the launcher for the lab server.
//
// On first launch it copies the bundled Python into ~/Library/Application Support/MISTER PLIS,
// clones the repository there (asking for a GitHub token if needed), creates .venv and installs
// requirements.lock (pinned, checked). Then it runs `python -m mister_plis`, restarts it if it stops, keeps the Mac
// from idle-sleeping, and shows a dock icon with a menu.
//
// The server's code stays a normal git checkout, so "Sync with git" in the web interface keeps
// working exactly as before (git pull, pip install, the server replaces its own process).
// Only this launcher is fixed inside the app. Build with scripts/build_app.sh.
//
// For testing, MISTER_PLIS_HOME and MISTER_PLIS_REPO_URL override the folder and the repository
// (and turn off the login item and the old-service check).

import AppKit
import ServiceManagement
import SystemConfiguration

// MARK: - Paths and settings

let fm = FileManager.default
let env = ProcessInfo.processInfo.environment
let info = Bundle.main.infoDictionary ?? [:]
let testMode = env["MISTER_PLIS_HOME"] != nil

let homeDir = env["MISTER_PLIS_HOME"].map { URL(fileURLWithPath: $0) }
    ?? fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("MISTER PLIS")
let repoURL = env["MISTER_PLIS_REPO_URL"] ?? (info["MPRepoURL"] as? String ?? "")
let runtimeDir = homeDir.appendingPathComponent("python")
let runtimePython = runtimeDir.appendingPathComponent("bin/python3")
let runtimeMarker = runtimeDir.appendingPathComponent("BUNDLED_VERSION")
let repoDir = homeDir.appendingPathComponent("MISTER_PLIS")
let venvDir = repoDir.appendingPathComponent(".venv")
let venvPython = venvDir.appendingPathComponent("bin/python")
let readyMarker = venvDir.appendingPathComponent(".mister-plis-ready")
let serverLog = repoDir.appendingPathComponent("logs/server.log")
let launcherLog = homeDir.appendingPathComponent("launcher.log")
let pidFile = homeDir.appendingPathComponent("server.pid")
let bundledPython = Bundle.main.resourceURL!.appendingPathComponent("python")
let bundledPythonVersion = ((try? String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("python-version.txt"),
                                         encoding: .utf8)) ?? "?").trimmingCharacters(in: .whitespacesAndNewlines)
let oldAgentLabel = "com.misterplis.server"
let oldAgentPlist = fm.homeDirectoryForCurrentUser.appendingPathComponent("Library/LaunchAgents/\(oldAgentLabel).plist")
let git = "/usr/bin/git"
let keychainOnly = ["-c", "credential.helper=", "-c", "credential.helper=osxkeychain"]
let tokenPage = URL(string: "https://github.com/settings/personal-access-tokens/new")!
let maxLogBytes = 20_000_000

var repoName: String {
    let last = URL(string: repoURL)?.lastPathComponent ?? (repoURL as NSString).lastPathComponent
    return last.hasSuffix(".git") ? String(last.dropLast(4)) : last
}
var repoHost: String { URL(string: repoURL)?.host ?? "github.com" }
var usesToken: Bool { repoURL.hasPrefix("https://") }

// MARK: - Helpers

func log(_ text: String) {
    let stamp = ISO8601DateFormatter.string(from: Date(), timeZone: .current, formatOptions: [.withFullDate, .withTime, .withColonSeparatorInTime, .withSpaceBetweenDateAndTime])
    let data = Data("\(stamp)  \(text)\n".utf8)
    try? fm.createDirectory(at: homeDir, withIntermediateDirectories: true)
    if let h = FileHandle(forWritingAtPath: launcherLog.path) {
        h.seekToEndOfFile(); h.write(data); try? h.close()
    } else {
        try? data.write(to: launcherLog)
    }
}

func childEnvironment() -> [String: String] {
    var e = env
    for k in ["PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__", "MISTER_PLIS_HOME", "MISTER_PLIS_REPO_URL"] {
        e.removeValue(forKey: k)
    }
    e["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin"
    e["PYTHONUNBUFFERED"] = "1"
    e["GIT_TERMINAL_PROMPT"] = "0"  // git must fail, not wait for a password nobody can type
    // How the server was installed (Settings → Server & updates). MISTER_PLIS_HOME is removed above: here it is this
    // launcher's own test folder, so the server's instance folder stays its checkout.
    e["MISTER_PLIS_INSTALL"] = "mac-app"
    // The lab file baked in at build time (MISTER_PLIS_LAB_FILE): the server applies it on its first start, while it
    // isn't set up yet, and ignores it afterwards (docs/LAB_SETUP_PLAN.md). config.toml's lab_file or the variable win.
    if e["MISTER_PLIS_LAB_FILE"] == nil, let labFile = info["MPLabFile"] as? String, !labFile.isEmpty {
        e["MISTER_PLIS_LAB_FILE"] = labFile
    }
    return e
}

var setupChild: Process?  // the command setup is waiting on, stopped if the app quits

/// Run a command to completion, returning its exit code and combined output. `input` is sent to
/// stdin and never logged (it can hold the token); with `quiet` the output isn't logged either.
@discardableResult
func run(_ exe: String, _ args: [String], cwd: URL? = nil, input: String? = nil, quiet: Bool = false) -> (code: Int32, out: String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: exe)
    p.arguments = args
    p.currentDirectoryURL = cwd ?? homeDir
    p.environment = childEnvironment()
    let out = Pipe(), stdin = Pipe()
    p.standardOutput = out
    p.standardError = out
    p.standardInput = input == nil ? FileHandle.nullDevice : stdin
    do { try p.run() } catch {
        log("$ \(exe) \(args.joined(separator: " ")) — could not start: \(error.localizedDescription)")
        return (-1, error.localizedDescription)
    }
    setupChild = p
    if let input {
        stdin.fileHandleForWriting.write(Data(input.utf8))
        try? stdin.fileHandleForWriting.close()
    }
    let text = String(decoding: out.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
    p.waitUntilExit()
    setupChild = nil
    log("$ \(exe) \(args.joined(separator: " ")) → exit \(p.terminationStatus)" + (text.isEmpty || quiet ? "" : "\n" + text.trimmingCharacters(in: .newlines)))
    return (p.terminationStatus, text)
}

func lastLines(_ text: String, _ n: Int = 8) -> String {
    text.split(separator: "\n", omittingEmptySubsequences: true).suffix(n).joined(separator: "\n")
}

func gitInstalled() -> Bool {
    // Don't call /usr/bin/git to find out: without the tools it pops up the installer itself.
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/xcode-select")
    p.arguments = ["-p"]
    let out = Pipe()
    p.standardOutput = out
    p.standardError = FileHandle.nullDevice
    guard (try? p.run()) != nil else { return false }
    let dir = String(decoding: out.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
    p.waitUntilExit()
    return p.terminationStatus == 0 && fm.isExecutableFile(atPath: dir + "/usr/bin/git")
}

func lanIP() -> String? {
    var list: UnsafeMutablePointer<ifaddrs>?
    guard getifaddrs(&list) == 0, let first = list else { return nil }
    defer { freeifaddrs(list) }
    for ptr in sequence(first: first, next: { $0.pointee.ifa_next }) {
        let a = ptr.pointee
        let flags = Int32(a.ifa_flags)
        guard let sa = a.ifa_addr, sa.pointee.sa_family == UInt8(AF_INET),
              flags & IFF_UP != 0, flags & IFF_LOOPBACK == 0,
              String(cString: a.ifa_name).hasPrefix("en") else { continue }
        var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
        if getnameinfo(sa, socklen_t(sa.pointee.sa_len), &host, socklen_t(host.count), nil, 0, NI_NUMERICHOST) == 0 {
            return String(cString: host)
        }
    }
    return nil
}

func portSuffix(_ port: Int) -> String { port == 80 ? "" : ":\(port)" }

func networkAddress(_ port: Int) -> String {
    let name = (SCDynamicStoreCopyLocalHostName(nil) as String?) ?? ProcessInfo.processInfo.hostName
    return "http://\(name).local\(portSuffix(port))"
}

enum SetupError: Error {
    case cancelled
    case failed(String)
}

func check(_ r: (code: Int32, out: String), _ message: String) throws {
    if r.code != 0 { throw SetupError.failed(message + "\n\n" + lastLines(r.out)) }
}

// MARK: - Setup window

final class SetupWindow {
    let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 480, height: 140),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
    let status = NSTextField(labelWithString: "")
    let detail = NSTextField(wrappingLabelWithString: "")
    let bar = NSProgressIndicator()

    init() {
        window.title = "MISTER PLIS"
        window.isReleasedWhenClosed = false
        let icon = NSImageView(image: NSApp.applicationIconImage)
        icon.translatesAutoresizingMaskIntoConstraints = false
        let title = NSTextField(labelWithString: "Setting up MISTER PLIS")
        title.font = .boldSystemFont(ofSize: 15)
        detail.font = .systemFont(ofSize: 11)
        detail.textColor = .secondaryLabelColor
        detail.preferredMaxLayoutWidth = 360
        bar.style = .bar
        bar.isIndeterminate = true
        let text = NSStackView(views: [title, status, bar, detail])
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 6
        let row = NSStackView(views: [icon, text])
        row.alignment = .top
        row.spacing = 16
        row.edgeInsets = NSEdgeInsets(top: 20, left: 20, bottom: 20, right: 20)
        window.contentView = row
        NSLayoutConstraint.activate([
            icon.widthAnchor.constraint(equalToConstant: 64), icon.heightAnchor.constraint(equalToConstant: 64),
            bar.widthAnchor.constraint(equalToConstant: 360), text.widthAnchor.constraint(equalToConstant: 360),
        ])
    }

    func show(_ message: String, _ note: String) {
        status.stringValue = message
        detail.stringValue = note
        bar.startAnimation(nil)
        if !window.isVisible {
            window.center()
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    func hide() {
        bar.stopAnimation(nil)
        window.orderOut(nil)
    }
}

// MARK: - App

enum State {
    case settingUp(String)
    case starting
    case running
    case restarting(Int)
    case stopped(String)
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    var state = State.settingUp("starting…")
    var server: Process?
    var port = 8000
    var startedAt = Date()
    var failures = 0
    var generation = 0          // bumps on every start/stop, so stale timers do nothing
    var stopping = false
    var quitting = false
    var systemShuttingDown = false
    var setupDone = false
    var freshInstall = false
    var openBrowserWhenRunning = true
    var activity: NSObjectProtocol?
    var sigterm: DispatchSourceSignal?
    let serverMenu = NSMenu(title: "Server")
    lazy var setupWindow = SetupWindow()
    let work = DispatchQueue(label: "com.misterplis.setup")

    // MARK: Launch

    func applicationWillFinishLaunching(_ note: Notification) {
        // Started as a login item: don't pop up a browser window at every boot.
        if let ev = NSAppleEventManager.shared().currentAppleEvent,
           ev.eventID == AEEventID(kAEOpenApplication),
           ev.paramDescriptor(forKeyword: AEKeyword(keyAEPropData))?.enumCodeValue == OSType(keyAELaunchedAsLogInItem) {
            openBrowserWhenRunning = false
        }
    }

    func applicationDidFinishLaunching(_ note: Notification) {
        NSApp.setActivationPolicy(.regular)
        buildMainMenu()
        // Keeps the Mac from idle-sleeping (the display may still sleep) and stops App Nap.
        activity = ProcessInfo.processInfo.beginActivity(options: [.userInitiated, .idleSystemSleepDisabled],
                                                         reason: "MISTER PLIS is serving the lab network")
        NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(willPowerOff),
                                                          name: NSWorkspace.willPowerOffNotification, object: nil)
        signal(SIGTERM, SIG_IGN)
        let src = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
        src.setEventHandler { [weak self] in
            self?.quitting = true
            self?.stopServer { exit(0) }
        }
        src.resume()
        sigterm = src
        log("Launcher started (Python \(bundledPythonVersion), repository \(repoURL))")

        if !testMode && fm.fileExists(atPath: oldAgentPlist.path) && !removeOldService() {
            quitting = true
            NSApp.terminate(nil)
            return
        }
        work.async { self.setUp() }
    }

    /// The service from scripts/install_service.sh would fight the app for the port.
    func removeOldService() -> Bool {
        let a = NSAlert()
        a.messageText = "MISTER PLIS is also installed as a background service"
        a.informativeText = "It was set up earlier with scripts/install_service.sh and uses the same port. "
            + "This app replaces it. Remove the old service?"
        a.addButton(withTitle: "Remove Old Service")
        a.addButton(withTitle: "Quit")
        NSApp.activate(ignoringOtherApps: true)
        guard a.runModal() == .alertFirstButtonReturn else { return false }
        run("/bin/launchctl", ["bootout", "gui/\(getuid())/\(oldAgentLabel)"])
        try? fm.removeItem(at: oldAgentPlist)
        return true
    }

    // MARK: Setup (runs on `work`)

    func progress(_ message: String, _ note: String = "") {
        DispatchQueue.main.async {
            self.state = .settingUp(message)
            self.setupWindow.show(message, note)
        }
    }

    func setUp() {
        do {
            try fm.createDirectory(at: homeDir, withIntermediateDirectories: true)
            try ensureGit()
            try ensureRuntime()
            try ensureCheckout()
            try ensureVenv()
            DispatchQueue.main.async { self.setupFinished() }
        } catch SetupError.cancelled {
            DispatchQueue.main.async { self.quitting = true; NSApp.terminate(nil) }
        } catch SetupError.failed(let message) {
            log("Setup failed: \(message)")
            DispatchQueue.main.async { self.setupFailed(message) }
        } catch {
            log("Setup failed: \(error)")
            DispatchQueue.main.async { self.setupFailed(error.localizedDescription) }
        }
    }

    func ensureGit() throws {
        if gitInstalled() { return }
        progress("Installing Apple’s Command Line Tools (for git)…",
                 "Click “Install” in the window that opened and wait until it finishes — "
                 + "this can take 10–20 minutes. Setup continues by itself afterwards.")
        run("/usr/bin/xcode-select", ["--install"])
        while !gitInstalled() {
            if quitting { throw SetupError.cancelled }
            Thread.sleep(forTimeInterval: 5)
        }
    }

    func ensureRuntime() throws {
        let installed = (try? String(contentsOf: runtimeMarker, encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines)
        if installed == bundledPythonVersion && fm.isExecutableFile(atPath: runtimePython.path) { return }
        progress("Copying Python \(bundledPythonVersion)…")
        try? fm.removeItem(at: runtimeDir)
        try fm.copyItem(at: bundledPython, to: runtimeDir)
        run("/usr/bin/xattr", ["-dr", "com.apple.quarantine", runtimeDir.path])
        try bundledPythonVersion.write(to: runtimeMarker, atomically: true, encoding: .utf8)
        try? fm.removeItem(at: venvDir)  // it pointed at the previous Python
    }

    func ensureCheckout() throws {
        if fm.fileExists(atPath: repoDir.appendingPathComponent(".git").path) { return }
        guard !repoURL.isEmpty else {
            throw SetupError.failed("This copy of the app doesn’t say which repository to use. Build it again with scripts/build_app.sh.")
        }
        freshInstall = true
        let partial = homeDir.appendingPathComponent("MISTER_PLIS.partial")
        var asked = false
        var problem: (message: String, isToken: Bool)?
        while true {
            // The first try doesn't ask: the Keychain may already hold a token, or the repo is public.
            if let p = problem {
                let shown = asked ? p.message : nil
                guard let token = DispatchQueue.main.sync(execute: { askForToken(problem: shown) }) else {
                    throw SetupError.cancelled
                }
                asked = true
                storeToken(token)
            }
            progress("Downloading \(repoName)…", repoURL)
            try? fm.removeItem(at: partial)
            let r = run(git, keychainOnly + ["clone", repoURL, partial.path])
            if r.code == 0 { break }
            let failure = usesToken ? describeGitFailure(r.out) : nil
            if let f = failure, !f.isToken { throw SetupError.failed(f.message) }
            if failure == nil { try check(r, "Couldn’t download \(repoURL).") }
            problem = failure
        }
        // Updates ("Sync with git") read the token from the Keychain too.
        run(git, ["config", "--local", "credential.helper", ""], cwd: partial)
        run(git, ["config", "--local", "--add", "credential.helper", "osxkeychain"], cwd: partial)
        try fm.moveItem(at: partial, to: repoDir)
    }

    /// nil = something else went wrong (show git's own error).
    func describeGitFailure(_ out: String) -> (message: String, isToken: Bool)? {
        let o = out.lowercased()
        if o.contains("could not resolve host") || o.contains("timed out") {
            return ("Can’t reach \(repoHost) — check this Mac’s internet connection, then try again.", false)
        }
        if o.contains("could not read username") || o.contains("authentication failed")
            || o.contains("not found") || o.contains("403") || o.contains("terminal prompts disabled") {
            return ("GitHub didn’t accept the token, or it has no access to \(repoName).", true)
        }
        return nil
    }

    func ensureVenv() throws {
        if fm.fileExists(atPath: readyMarker.path) && fm.isExecutableFile(atPath: venvPython.path) { return }
        progress("Installing Python packages…", "This takes a few minutes the first time.")
        if !fm.isExecutableFile(atPath: venvPython.path) {
            try? fm.removeItem(at: venvDir)
            try check(run(runtimePython.path, ["-m", "venv", ".venv"], cwd: repoDir), "Couldn’t create the Python environment.")
        }
        try check(run(venvPython.path, ["-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"], cwd: repoDir),
                  "Couldn’t update pip. Check the internet connection, then try again.")
        // exactly the pinned versions, checked against their checksums (requirements.lock, docs/RELEASES.md); an older
        // checkout without the lock file: requirements.txt
        let pinned = fm.fileExists(atPath: repoDir.appendingPathComponent("requirements.lock").path)
        let packages = pinned ? ["--require-hashes", "-r", "requirements.lock"] : ["-r", "requirements.txt"]
        try check(run(venvPython.path, ["-m", "pip", "install", "--disable-pip-version-check"] + packages, cwd: repoDir),
                  "Couldn’t install the Python packages. Check the internet connection, then try again.")
        try Data().write(to: readyMarker)
    }

    func setupFinished() {
        setupDone = true
        setupWindow.hide()
        if freshInstall && !testMode && SMAppService.mainApp.status != .enabled {
            do { try SMAppService.mainApp.register() } catch { log("Couldn’t add the login item: \(error)") }
        }
        startServer()
    }

    func setupFailed(_ message: String) {
        setupWindow.hide()
        state = .stopped("setup didn’t finish")
        while true {
            let a = NSAlert()
            a.alertStyle = .warning
            a.messageText = "MISTER PLIS couldn’t finish setting up"
            a.informativeText = message
            a.addButton(withTitle: "Try Again")
            a.addButton(withTitle: "Quit")
            a.addButton(withTitle: "Show Log")
            NSApp.activate(ignoringOtherApps: true)
            switch a.runModal() {
            case .alertFirstButtonReturn: work.async { self.setUp() }; return
            case .alertThirdButtonReturn: openInConsole(launcherLog)
            default: quitting = true; NSApp.terminate(nil); return
            }
        }
    }

    // MARK: GitHub token (main thread)

    func askForToken(problem: String?) -> String? {
        while true {
            let a = NSAlert()
            a.messageText = problem == nil ? "Connect to GitHub" : "That didn’t work"
            a.informativeText = (problem.map { $0 + "\n\n" } ?? "")
                + "MISTER PLIS gets its code and updates from the private repository \(repoName). "
                + "Paste a GitHub token that can read it — it’s kept in this Mac’s Keychain.\n\n"
                + "To make one: “Create Token on GitHub…” → Repository access: Only select repositories → \(repoName); "
                + "Permissions → Contents: Read-only."
            let field = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 340, height: 24))
            field.placeholderString = "github_pat_…"
            a.accessoryView = field
            a.addButton(withTitle: "Continue")
            a.addButton(withTitle: "Cancel")
            a.addButton(withTitle: "Create Token on GitHub…")
            a.window.initialFirstResponder = field
            NSApp.activate(ignoringOtherApps: true)
            switch a.runModal() {
            case .alertFirstButtonReturn:
                let token = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
                if !token.isEmpty { return token }
            case .alertThirdButtonReturn:
                NSWorkspace.shared.open(tokenPage)
            default:
                return nil
            }
        }
    }

    func storeToken(_ token: String) {
        run(git, keychainOnly + ["credential", "reject"], input: "protocol=https\nhost=\(repoHost)\n\n")
        run(git, keychainOnly + ["credential", "approve"],
            input: "protocol=https\nhost=\(repoHost)\nusername=x-access-token\npassword=\(token)\n\n")
    }

    @objc func changeToken() {
        guard let token = askForToken(problem: nil) else { return }
        work.async {
            self.storeToken(token)
            let r = run(git, ["ls-remote", "--heads", "origin"], cwd: repoDir)
            DispatchQueue.main.async {
                let a = NSAlert()
                a.messageText = r.code == 0 ? "Token saved" : "Token saved, but GitHub didn’t accept it"
                a.informativeText = r.code == 0 ? "“Sync with git” will use the new token."
                    : (self.describeGitFailure(r.out)?.message ?? lastLines(r.out))
                a.runModal()
            }
        }
    }

    // MARK: Server

    func startServer() {
        guard server == nil, setupDone, !quitting else { return }
        generation += 1
        killStaleServer()
        try? fm.createDirectory(at: serverLog.deletingLastPathComponent(), withIntermediateDirectories: true)
        rotateLog()
        port = readPort()
        state = .starting
        let p = Process()
        p.executableURL = venvPython
        p.arguments = ["-m", "mister_plis"]
        p.currentDirectoryURL = repoDir
        p.environment = childEnvironment()
        p.qualityOfService = .userInitiated
        // O_APPEND, so emptying the log while it runs works.
        let fd = open(serverLog.path, O_WRONLY | O_APPEND | O_CREAT, 0o644)
        let out = fd >= 0 ? FileHandle(fileDescriptor: fd, closeOnDealloc: true) : FileHandle.nullDevice
        p.standardOutput = out
        p.standardError = out
        p.standardInput = FileHandle.nullDevice
        p.terminationHandler = { proc in DispatchQueue.main.async { self.serverExited(proc) } }
        do {
            try p.run()
        } catch {
            log("Couldn’t start the server: \(error)")
            server = nil
            scheduleRestart(reason: "couldn’t start")
            return
        }
        server = p
        startedAt = Date()
        try? "\(p.processIdentifier)".write(to: pidFile, atomically: true, encoding: .utf8)
        log("Server started (pid \(p.processIdentifier), port \(port))")
        waitUntilAnswering(p, generation: generation, tries: 120)
    }

    func readPort() -> Int {
        let r = run(venvPython.path, ["-c", "from mister_plis.config import settings; print(settings.port)"], cwd: repoDir)
        return Int(r.out.trimmingCharacters(in: .whitespacesAndNewlines)) ?? 8000
    }

    func waitUntilAnswering(_ p: Process, generation gen: Int, tries: Int) {
        guard gen == generation, p === server, p.isRunning else { return }
        var req = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/api/version")!)
        req.timeoutInterval = 2
        URLSession.shared.dataTask(with: req) { _, response, _ in
            DispatchQueue.main.async {
                guard gen == self.generation, p === self.server else { return }
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    self.state = .running
                    if self.openBrowserWhenRunning {
                        self.openBrowserWhenRunning = false
                        self.openInBrowser()
                    }
                } else if tries > 1 {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.waitUntilAnswering(p, generation: gen, tries: tries - 1) }
                }
            }
        }.resume()
    }

    func serverExited(_ p: Process) {
        guard p === server, !stopping else { return }
        server = nil
        try? fm.removeItem(at: pidFile)
        if quitting { return }
        let uptime = Date().timeIntervalSince(startedAt)
        log("Server exited with status \(p.terminationStatus) after \(Int(uptime)) s")
        failures = uptime > 60 ? 1 : failures + 1
        scheduleRestart(reason: "stopped unexpectedly")
    }

    func scheduleRestart(reason: String) {
        let delay = min(60, 5 << min(max(failures - 1, 0), 4))  // 5, 10, 20, 40, 60 s
        state = .restarting(delay)
        generation += 1
        let gen = generation
        DispatchQueue.main.asyncAfter(deadline: .now() + .seconds(delay)) {
            if gen == self.generation { self.startServer() }
        }
    }

    func stopServer(_ done: @escaping () -> Void) {
        generation += 1
        guard let p = server, p.isRunning else { server = nil; done(); return }
        stopping = true
        p.terminate()
        DispatchQueue.global().async {
            let deadline = Date().addingTimeInterval(10)
            while p.isRunning && Date() < deadline { usleep(100_000) }
            if p.isRunning { kill(p.processIdentifier, SIGKILL); p.waitUntilExit() }
            DispatchQueue.main.async {
                self.server = nil
                self.stopping = false
                try? fm.removeItem(at: pidFile)
                log("Server stopped")
                done()
            }
        }
    }

    /// A server left behind by a launcher that was force-quit would still hold the port.
    func killStaleServer() {
        guard let pid = (try? String(contentsOf: pidFile, encoding: .utf8)).flatMap({ Int32($0.trimmingCharacters(in: .whitespacesAndNewlines)) }),
              kill(pid, 0) == 0 else { return }
        let cmd = run("/bin/ps", ["-o", "command=", "-p", "\(pid)"]).out
        guard cmd.contains("mister_plis") else { return }
        log("Stopping a server left over from before (pid \(pid))")
        kill(pid, SIGTERM)
        for _ in 0..<50 where kill(pid, 0) == 0 { usleep(100_000) }
        if kill(pid, 0) == 0 { kill(pid, SIGKILL) }
    }

    func rotateLog() {
        guard let size = (try? fm.attributesOfItem(atPath: serverLog.path))?[.size] as? Int, size > maxLogBytes else { return }
        let old = serverLog.appendingPathExtension("1")
        try? fm.removeItem(at: old)
        try? fm.moveItem(at: serverLog, to: old)
    }

    // MARK: Quit

    @objc func willPowerOff(_ note: Notification) { systemShuttingDown = true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if !systemShuttingDown && !quitting && server != nil {
            let a = NSAlert()
            a.messageText = "Stop MISTER PLIS?"
            a.informativeText = "Nobody on the network can use MISTER PLIS until the app is opened again."
            a.addButton(withTitle: "Keep Running")
            a.addButton(withTitle: "Stop and Quit")
            NSApp.activate(ignoringOtherApps: true)
            if a.runModal() != .alertSecondButtonReturn { return .terminateCancel }
        }
        quitting = true
        setupChild?.terminate()
        stopServer { NSApp.reply(toApplicationShouldTerminate: true) }
        return .terminateLater
    }

    // MARK: Dock and menus

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        // Clicking the dock icon (or opening the app again) opens the web page.
        if case .running = state { openInBrowser() } else if case .settingUp = state { setupWindow.window.makeKeyAndOrderFront(nil) }
        return false
    }

    func applicationDockMenu(_ sender: NSApplication) -> NSMenu? {
        let m = NSMenu()
        fill(m)
        return m
    }

    func menuNeedsUpdate(_ menu: NSMenu) { fill(menu) }

    var statusText: String {
        switch state {
        case .settingUp(let s): return "Setting up: \(s)"
        case .starting: return "Starting…"
        case .running: return "Running at \(networkAddress(port))"
        case .restarting(let s): return "Stopped unexpectedly — restarting in \(s) s"
        case .stopped(let s): return "Not running — \(s)"
        }
    }

    func fill(_ m: NSMenu) {
        m.removeAllItems()
        m.autoenablesItems = false
        var running = false
        if case .running = state { running = true }
        func add(_ title: String, _ action: Selector?, enabled: Bool = true) -> NSMenuItem {
            let item = NSMenuItem(title: title, action: action, keyEquivalent: "")
            item.target = self
            item.isEnabled = enabled && action != nil
            m.addItem(item)
            return item
        }
        _ = add(statusText, nil)
        if running, let ip = lanIP() { _ = add("or http://\(ip)\(portSuffix(port))", nil) }
        m.addItem(.separator())
        _ = add("Open MISTER PLIS", #selector(openInBrowser), enabled: running)
        _ = add("Copy Address", #selector(copyAddress), enabled: running)
        m.addItem(.separator())
        _ = add("Restart Server", #selector(restartServer), enabled: setupDone)
        _ = add("Show Log", #selector(showLog))
        _ = add("Show Files in Finder", #selector(showFiles))
        _ = add("Change GitHub Token…", #selector(changeToken), enabled: setupDone && usesToken)
        m.addItem(.separator())
        let login = add("Start at Login", #selector(toggleLoginItem), enabled: !testMode)
        login.state = SMAppService.mainApp.status == .enabled ? .on : .off
        m.addItem(.separator())
        var settingUp = false
        if case .settingUp = state { settingUp = true }
        _ = add("Remove App Data and Quit…", #selector(removeAppData), enabled: !settingUp)
    }

    func buildMainMenu() {
        let main = NSMenu()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About MISTER PLIS", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide MISTER PLIS", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit MISTER PLIS", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        // An Edit menu is what makes ⌘V work in the token field.
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        serverMenu.delegate = self
        for sub in [appMenu, edit, serverMenu] {
            let item = NSMenuItem()
            item.submenu = sub
            main.addItem(item)
        }
        NSApp.mainMenu = main
    }

    @objc func openInBrowser() {
        NSWorkspace.shared.open(URL(string: "http://localhost\(portSuffix(port))")!)
    }

    @objc func copyAddress() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(networkAddress(port), forType: .string)
    }

    @objc func restartServer() {
        failures = 0
        stopServer { self.startServer() }
    }

    func openInConsole(_ url: URL) {
        let console = URL(fileURLWithPath: "/System/Applications/Utilities/Console.app")
        NSWorkspace.shared.open([url], withApplicationAt: console, configuration: NSWorkspace.OpenConfiguration())
    }

    @objc func showLog() {
        openInConsole(fm.fileExists(atPath: serverLog.path) ? serverLog : launcherLog)
    }

    @objc func showFiles() {
        NSWorkspace.shared.activateFileViewerSelecting([fm.fileExists(atPath: repoDir.path) ? repoDir : homeDir])
    }

    @objc func toggleLoginItem() {
        let service = SMAppService.mainApp
        do {
            if service.status == .enabled { try service.unregister() } else { try service.register() }
        } catch {
            let a = NSAlert()
            a.messageText = "Couldn’t change Start at Login"
            a.informativeText = "\(error.localizedDescription)\n\nYou can add MISTER PLIS by hand in System Settings → General → Login Items."
            a.runModal()
            SMAppService.openSystemSettingsLoginItems()
        }
        if service.status == .requiresApproval { SMAppService.openSystemSettingsLoginItems() }
    }

    // MARK: Remove app data

    @objc func removeAppData() {
        let a = NSAlert()
        a.alertStyle = .critical
        a.messageText = "Remove all MISTER PLIS data from this Mac?"
        a.informativeText = "This stops the server and deletes \(homeDir.path) — the code, Python, packages, "
            + "config.toml, every result and upload, and the logs — removes the GitHub token from the Keychain "
            + "and the login item, then quits.\n\nIt can’t be undone. Afterwards, move the app itself to the Trash."
        a.addButton(withTitle: "Cancel")
        a.addButton(withTitle: "Remove and Quit")
        a.buttons[1].hasDestructiveAction = true
        NSApp.activate(ignoringOtherApps: true)
        guard a.runModal() == .alertSecondButtonReturn else { return }
        quitting = true
        setupChild?.terminate()
        stopServer {
            self.work.async {
                if usesToken { self.forgetToken() }
                if !testMode { try? SMAppService.mainApp.unregister() }
                var error: Error?
                do { try fm.removeItem(at: homeDir) } catch let e { error = e }
                DispatchQueue.main.async {
                    if let error {
                        let b = NSAlert()
                        b.messageText = "Couldn’t remove everything"
                        b.informativeText = "\(error.localizedDescription)\n\nDelete \(homeDir.path) in Finder to finish."
                        b.runModal()
                        NSWorkspace.shared.activateFileViewerSelecting([homeDir])
                    }
                    NSApp.terminate(nil)
                }
            }
        }
    }

    /// Erase the Keychain entry only if it's the token this app saved, never someone's own GitHub login.
    func forgetToken() {
        let query = "protocol=https\nhost=\(repoHost)\n\n"
        let r = run(git, ["credential-osxkeychain", "get"], input: query, quiet: true)
        guard r.code == 0, r.out.split(separator: "\n").contains("username=x-access-token") else { return }
        run(git, ["credential-osxkeychain", "erase"], input: query)
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
