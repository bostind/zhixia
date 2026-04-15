use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::Manager;

pub struct PythonProcessState {
    pub child: Mutex<Option<Child>>,
}

fn resolve_backend_exe(app_handle: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    // 0. 开发模式最优先：如果 ZHIXIA_PYTHON_DIR 存在且包含 main_api.py，直接使用
    if let Ok(dir) = std::env::var("ZHIXIA_PYTHON_DIR") {
        let script = std::path::PathBuf::from(dir.trim()).join("main_api.py");
        if script.exists() {
            return Ok(script);
        }
    }

    // 1. 环境变量覆盖：如果直接指向了 bundled backend exe
    if let Ok(exe) = std::env::var("ZHIXIA_PYTHON_EXE") {
        let p = std::path::PathBuf::from(exe.trim());
        if p.exists() && p.file_name().map(|n| n == "zhixia-backend.exe").unwrap_or(false) {
            return Ok(p);
        }
    }

    // 2. 生产包：resources/zhixia-backend/zhixia-backend.exe
    let resource_dir = app_handle
        .path()
        .resource_dir()
        .map_err(|e| e.to_string())?;
    let candidates = [
        resource_dir.join("zhixia-backend").join("zhixia-backend.exe"),
        resource_dir.join("python-dist").join("zhixia-backend").join("zhixia-backend.exe"),
    ];
    for bundled in &candidates {
        if bundled.exists() {
            return Ok(bundled.clone());
        }
    }

    // 3. 开发模式：相对于可执行文件的路径
    if let Ok(exe_path) = std::env::current_exe() {
        let exe_dir = exe_path.parent().ok_or("No exe parent")?;
        let candidates = [
            exe_dir.join("python"),
            exe_dir.parent().map(|d| d.join("python")).unwrap_or_default(),
            exe_dir.parent().and_then(|d| d.parent()).map(|d| d.join("python")).unwrap_or_default(),
            exe_dir.parent().and_then(|d| d.parent()).and_then(|d| d.parent()).map(|d| d.join("src-tauri").join("python")).unwrap_or_default(),
        ];
        for c in &candidates {
            if c.exists() && c.join("main_api.py").exists() {
                return Ok(c.join("main_api.py"));
            }
        }
    }

    Err("Could not find bundled backend exe or python directory. Set ZHIXIA_PYTHON_EXE or ensure resources/zhixia-backend/ exists.".to_string())
}

fn pipe_child_output(mut child: Child) -> Child {
    if let Some(stdout) = child.stdout.take() {
        std::thread::spawn(move || {
            let reader = BufReader::new(stdout);
            for line in reader.lines() {
                if let Ok(line) = line {
                    log::info!("[Python stdout] {}", line);
                }
            }
        });
    }
    if let Some(stderr) = child.stderr.take() {
        std::thread::spawn(move || {
            let reader = BufReader::new(stderr);
            for line in reader.lines() {
                if let Ok(line) = line {
                    log::error!("[Python stderr] {}", line);
                }
            }
        });
    }
    child
}

fn start_python_server(app_handle: &tauri::AppHandle) -> Result<Child, String> {
    let app_data_dir = app_handle
        .path()
        .app_local_data_dir()
        .map_err(|e| e.to_string())?;
    
    // 创建数据目录
    let data_dir = app_data_dir.join("data");
    std::fs::create_dir_all(&data_dir).map_err(|e| e.to_string())?;

    let backend = resolve_backend_exe(app_handle)?;
    let is_bundled = backend.file_name().map(|n| n == "zhixia-backend.exe").unwrap_or(false);

    let child = if is_bundled {
        let backend_dir = backend.parent().ok_or("Invalid backend path")?;
        Command::new(&backend)
            .env("ZHIXIA_DATA_DIR", &data_dir)
            .env("ZHIXIA_API_PORT", "8765")
            .env("PYTHONIOENCODING", "utf-8")
            .current_dir(&backend_dir)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to start bundled backend: {}", e))?
    } else {
        // 开发阶段：backend 路径指向 main_api.py，使用系统 python 运行
        let python_dir = backend.parent().ok_or("Invalid script path")?;
        let python_exe = std::env::var("ZHIXIA_PYTHON_EXE")
            .unwrap_or_else(|_| "python".to_string());
        Command::new(&python_exe)
            .arg(&backend)
            .env("ZHIXIA_DATA_DIR", &data_dir)
            .env("ZHIXIA_API_PORT", "8765")
            .env("PYTHONIOENCODING", "utf-8")
            .current_dir(&python_dir)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to start Python: {}", e))?
    };

    Ok(pipe_child_output(child))
}

fn wait_for_python_health(port: u16, timeout_secs: u64) -> Result<(), String> {
    let start = std::time::Instant::now();
    let client = reqwest::blocking::Client::new();
    let url = format!("http://127.0.0.1:{}/health", port);
    
    while start.elapsed().as_secs() < timeout_secs {
        if let Ok(resp) = client.get(&url).timeout(std::time::Duration::from_secs(2)).send() {
            if resp.status().is_success() {
                return Ok(());
            }
        }
        std::thread::sleep(std::time::Duration::from_millis(500));
    }
    
    Err("Python API health check timed out".to_string())
}

#[tauri::command]
fn open_file(path: String) -> Result<(), String> {
    // 使用 tauri-plugin-opener 打开文件
    tauri_plugin_opener::open_path(path, None::<&str>)
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn open_folder(path: String) -> Result<(), String> {
    let p = std::path::PathBuf::from(&path);
    if let Some(_parent) = p.parent() {
        #[cfg(target_os = "windows")]
        {
            // Windows: 使用 explorer /select 高亮文件
            let _ = std::process::Command::new("explorer")
                .args(["/select,", &path])
                .spawn();
        }
        #[cfg(not(target_os = "windows"))]
        {
            let _ = tauri_plugin_opener::open_path(parent, None::<&str>);
        }
        Ok(())
    } else {
        Err("Invalid path".to_string())
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .max_file_size(10 * 1024 * 1024 /* 10MB */)
                .rotation_strategy(tauri_plugin_log::RotationStrategy::KeepAll)
                .targets([
                    tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::Stdout),
                    tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::LogDir {
                        file_name: Some("frontend".to_string()),
                    }),
                ])
                .build(),
        )
        .setup(|app| {
            let app_handle = app.handle().clone();
            
            // 启动 Python 进程
            let child = start_python_server(&app_handle)
                .map_err(|e| {
                    log::error!("[知匣] Failed to start Python server: {}", e);
                    e
                })
                .expect("Python server must start");
            
            // 等待 Python API 就绪
            wait_for_python_health(8765, 60)
                .map_err(|e| {
                    log::error!("[知匣] Python health check failed: {}", e);
                    e
                })
                .expect("Python API health check must pass");
            
            log::info!("[知匣] Python server is ready");
            
            // 保存进程句柄到 state
            app.manage(PythonProcessState {
                child: Mutex::new(Some(child)),
            });
            
            Ok(())
        })
        .on_window_event(|app, event| {
            // 窗口关闭时终止 Python 进程
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = app.try_state::<PythonProcessState>() {
                    if let Ok(mut child) = state.child.lock() {
                        if let Some(mut c) = child.take() {
                            let _ = c.kill();
                        }
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![open_file, open_folder])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
