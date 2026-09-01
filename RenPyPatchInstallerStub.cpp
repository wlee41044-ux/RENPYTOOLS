#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shlobj.h>
#include <filesystem>
#include <fstream>
#include <vector>
#include <string>
#include <cstdint>
#include <algorithm>
#include <iterator>
#include <cwctype>
#include <cstring>

namespace fs = std::filesystem;

static const char PKG_MAGIC[8] = {'R','P','T','P','K','G','0','1'};
static const char END_MAGIC[8] = {'R','P','T','E','N','D','0','1'};

static std::wstring widen_utf8(const std::string& s) {
    if (s.empty()) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), nullptr, 0);
    if (n <= 0) return L"";
    std::wstring out(static_cast<size_t>(n), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), out.data(), n);
    return out;
}

static std::wstring timestamp_now() {
    SYSTEMTIME st{};
    GetLocalTime(&st);
    wchar_t buf[64]{};
    swprintf_s(buf, L"%04u%02u%02u_%02u%02u%02u", st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond);
    return buf;
}

static bool looks_like_game_root(const fs::path& root) {
    std::error_code ec;
    fs::path game = root / L"game";
    if (!fs::is_directory(game, ec)) return false;

    for (const auto& entry : fs::directory_iterator(game, fs::directory_options::skip_permission_denied, ec)) {
        if (ec) break;
        if (!entry.is_regular_file(ec)) continue;
        auto ext = entry.path().extension().wstring();
        std::transform(ext.begin(), ext.end(), ext.begin(), [](wchar_t c) {
            return static_cast<wchar_t>(std::towlower(c));
        });
        if (ext == L".rpa" || ext == L".rpy" || ext == L".rpyc" || ext == L".rpym" || ext == L".rpymc") {
            return true;
        }
    }

    // A valid Ren'Py game can keep most scripts inside archives, so the game
    // directory itself is enough for fallback detection.
    return true;
}

static fs::path normalize_selected_root(fs::path p) {
    std::error_code ec;
    if (looks_like_game_root(p)) return p;
    if (p.filename() == L"game" && fs::is_directory(p, ec) && looks_like_game_root(p.parent_path())) {
        return p.parent_path();
    }
    return {};
}

static fs::path choose_folder(HWND owner) {
    BROWSEINFOW bi{};
    bi.hwndOwner = owner;
    bi.lpszTitle = L"Ren'Py 게임 폴더를 선택하세요. (game 폴더가 들어있는 위치)";
    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE;
    PIDLIST_ABSOLUTE pidl = SHBrowseForFolderW(&bi);
    if (!pidl) return {};

    wchar_t path[MAX_PATH]{};
    fs::path result;
    if (SHGetPathFromIDListW(pidl, path)) result = path;
    CoTaskMemFree(pidl);
    return normalize_selected_root(result);
}

static fs::path auto_find_game_root(const fs::path& exe_dir) {
    if (looks_like_game_root(exe_dir)) return exe_dir;
    if (!exe_dir.parent_path().empty() && looks_like_game_root(exe_dir.parent_path())) return exe_dir.parent_path();

    std::error_code ec;
    std::vector<fs::path> candidates;
    for (const auto& entry : fs::directory_iterator(exe_dir, fs::directory_options::skip_permission_denied, ec)) {
        if (ec) break;
        if (entry.is_directory(ec) && looks_like_game_root(entry.path())) candidates.push_back(entry.path());
    }
    if (candidates.size() == 1) return candidates.front();
    return {};
}

struct PackageFile {
    std::string relative_path;
    std::vector<char> data;
};

static bool read_exact(std::ifstream& in, void* dst, size_t size) {
    in.read(reinterpret_cast<char*>(dst), static_cast<std::streamsize>(size));
    return static_cast<size_t>(in.gcount()) == size;
}

template <typename T>
static bool read_num(std::ifstream& in, T& value) {
    return read_exact(in, &value, sizeof(T));
}

static bool load_package(const fs::path& exe_path, std::string& lang_dir, std::vector<PackageFile>& files, std::wstring& error) {
    std::ifstream in(exe_path, std::ios::binary);
    if (!in) {
        error = L"패치 실행 파일을 읽을 수 없습니다.";
        return false;
    }

    in.seekg(0, std::ios::end);
    std::streamoff file_size = in.tellg();
    if (file_size < 16) {
        error = L"패치 데이터가 없습니다.";
        return false;
    }

    in.seekg(file_size - 16);
    uint64_t archive_len = 0;
    char end_magic[8]{};
    if (!read_num(in, archive_len) || !read_exact(in, end_magic, 8) || std::memcmp(end_magic, END_MAGIC, 8) != 0) {
        error = L"유효한 RenPy Tools 독립 패치 파일이 아닙니다.";
        return false;
    }
    if (archive_len > static_cast<uint64_t>(file_size - 16)) {
        error = L"패치 데이터 길이가 잘못되었습니다.";
        return false;
    }

    std::streamoff start = file_size - 16 - static_cast<std::streamoff>(archive_len);
    in.seekg(start);
    char pkg_magic[8]{};
    if (!read_exact(in, pkg_magic, 8) || std::memcmp(pkg_magic, PKG_MAGIC, 8) != 0) {
        error = L"패치 데이터 헤더가 손상되었습니다.";
        return false;
    }

    uint32_t count = 0;
    uint16_t lang_len = 0;
    if (!read_num(in, count) || !read_num(in, lang_len) || lang_len == 0 || lang_len > 128 || count > 200000) {
        error = L"패치 데이터 형식이 올바르지 않습니다.";
        return false;
    }

    lang_dir.resize(lang_len);
    if (!read_exact(in, lang_dir.data(), lang_len)) {
        error = L"언어 정보를 읽지 못했습니다.";
        return false;
    }

    files.clear();
    files.reserve(count);
    for (uint32_t i = 0; i < count; ++i) {
        uint32_t path_len = 0;
        uint64_t data_len = 0;
        if (!read_num(in, path_len) || !read_num(in, data_len) || path_len == 0 || path_len > 4096 || data_len > 1024ULL * 1024ULL * 256ULL) {
            error = L"패치 파일 정보가 손상되었습니다.";
            return false;
        }

        PackageFile pf;
        pf.relative_path.resize(path_len);
        if (!read_exact(in, pf.relative_path.data(), path_len)) {
            error = L"패치 경로를 읽지 못했습니다.";
            return false;
        }

        pf.data.resize(static_cast<size_t>(data_len));
        if (data_len && !read_exact(in, pf.data.data(), static_cast<size_t>(data_len))) {
            error = L"패치 파일을 읽지 못했습니다.";
            return false;
        }
        files.push_back(std::move(pf));
    }
    return true;
}

static bool safe_relative(const fs::path& p) {
    if (p.empty() || p.is_absolute()) return false;
    for (const auto& part : p) {
        if (part == L".." || part == L".") return false;
    }
    return true;
}

static bool apply_package(
    const fs::path& root,
    const std::string& lang_dir_utf8,
    const std::vector<PackageFile>& files,
    fs::path& backup_out,
    std::wstring& error
) {
    std::error_code ec;
    fs::path game = root / L"game";
    if (!fs::is_directory(game, ec)) {
        error = L"선택한 위치에 game 폴더가 없습니다.";
        return false;
    }

    fs::path lang_dir = fs::path(widen_utf8(lang_dir_utf8));
    if (lang_dir.empty() || lang_dir.has_parent_path()) {
        error = L"패치 언어 폴더 정보가 올바르지 않습니다.";
        return false;
    }

    fs::path target = game / L"tl" / lang_dir;
    if (fs::exists(target, ec)) {
        fs::path backup_base = game / L"_RenPyTools_Backup";
        ec.clear();
        fs::create_directories(backup_base, ec);
        if (ec) {
            error = L"백업 폴더를 만들 수 없습니다.\n" + widen_utf8(ec.message());
            return false;
        }

        backup_out = backup_base / (lang_dir.wstring() + L"_" + timestamp_now());
        ec.clear();
        fs::rename(target, backup_out, ec);
        if (ec) {
            error = L"기존 번역 폴더 백업에 실패했습니다. 게임이 실행 중인지 확인하세요.\n" + widen_utf8(ec.message());
            return false;
        }
    }

    ec.clear();
    fs::create_directories(target, ec);
    if (ec) {
        error = L"번역 폴더를 만들 수 없습니다.\n" + widen_utf8(ec.message());
        return false;
    }

    for (const auto& pf : files) {
        fs::path rel = fs::path(widen_utf8(pf.relative_path));
        if (!safe_relative(rel)) {
            error = L"안전하지 않은 패치 경로가 포함되어 있습니다.";
            return false;
        }

        fs::path dest = target / rel;
        ec.clear();
        fs::create_directories(dest.parent_path(), ec);
        if (ec) {
            error = L"패치 하위 폴더 생성에 실패했습니다.\n" + widen_utf8(ec.message());
            return false;
        }

        std::ofstream out(dest, std::ios::binary | std::ios::trunc);
        if (!out) {
            error = L"패치 파일을 쓸 수 없습니다: " + dest.wstring();
            return false;
        }
        if (!pf.data.empty()) out.write(pf.data.data(), static_cast<std::streamsize>(pf.data.size()));
        if (!out.good()) {
            error = L"패치 파일 쓰기에 실패했습니다: " + dest.wstring();
            return false;
        }
    }

    // Activate the installed translation even when the original game has no
    // language selection UI. The file is deliberately outside tl/ so deferred
    // translation loading cannot prevent it from running.
    fs::path loader = game / L"renpytools_language.rpy";
    if (fs::exists(loader, ec)) {
        fs::path backup_base = game / L"_RenPyTools_Backup";
        ec.clear();
        fs::create_directories(backup_base, ec);
        if (!ec) {
            fs::path loader_backup = backup_base / (L"renpytools_language_" + timestamp_now() + L".rpy");
            std::error_code copy_ec;
            fs::copy_file(loader, loader_backup, fs::copy_options::overwrite_existing, copy_ec);
        }
    }

    std::ofstream loader_out(loader, std::ios::binary | std::ios::trunc);
    if (!loader_out) {
        error = L"번역 언어 활성화 파일을 쓸 수 없습니다.";
        return false;
    }
    loader_out << "# Generated by RenPy Tools v0.3.2\n";
    loader_out << "# Activates the language installed by RenPy Tools.\n";
    loader_out << "init 999 python:\n";
    loader_out << "    config.language = '" << lang_dir_utf8 << "'\n";
    if (!loader_out.good()) {
        error = L"번역 언어 활성화 파일 쓰기에 실패했습니다.";
        return false;
    }
    return true;
}

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);

    wchar_t module_path[32768]{};
    DWORD n = GetModuleFileNameW(nullptr, module_path, static_cast<DWORD>(std::size(module_path)));
    if (!n || n >= std::size(module_path)) {
        MessageBoxW(nullptr, L"실행 파일 경로를 확인할 수 없습니다.", L"RenPy Patch", MB_ICONERROR);
        CoUninitialize();
        return 1;
    }
    fs::path exe_path(module_path);

    std::string lang_dir;
    std::vector<PackageFile> files;
    std::wstring error;
    if (!load_package(exe_path, lang_dir, files, error)) {
        MessageBoxW(nullptr, error.c_str(), L"RenPy Patch", MB_ICONERROR);
        CoUninitialize();
        return 2;
    }

    fs::path root = auto_find_game_root(exe_path.parent_path());
    if (root.empty()) root = choose_folder(nullptr);
    if (root.empty()) {
        MessageBoxW(nullptr, L"게임 폴더를 찾지 못해 패치를 취소했습니다.", L"RenPy Patch", MB_ICONWARNING);
        CoUninitialize();
        return 3;
    }

    fs::path backup;
    if (!apply_package(root, lang_dir, files, backup, error)) {
        MessageBoxW(nullptr, error.c_str(), L"RenPy Patch", MB_ICONERROR);
        CoUninitialize();
        return 4;
    }

    std::wstring message = L"패치 적용이 완료되었습니다.\n\n게임: " + root.wstring();
    if (!backup.empty()) message += L"\n기존 패치 백업: " + backup.wstring();
    MessageBoxW(nullptr, message.c_str(), L"RenPy Patch", MB_ICONINFORMATION);
    CoUninitialize();
    return 0;
}
