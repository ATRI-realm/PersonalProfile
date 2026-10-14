/* ============================================================================
 *  loc.cpp  --  代码行统计工具 (Lines of Code Counter)
 * ----------------------------------------------------------------------------
 *  功能：
 *      递归扫描指定目录，统计 C / C++ / Java / Python 源文件的
 *      文件数(files)、函数数(functions)、空行(blank)、注释行(comment)、代码行(code)，
 *      并按语言分类汇总输出表格。
 *
 *  输入：
 *      命令行指定目录名；如果没有指定，则默认当前目录。
 *
 *  用法：
 *      loc                统计当前目录
 *      loc <目录>         统计指定目录
 *      loc <目录> -s      简化模式：blank / comment 列显示 "/"
 *      loc -h             显示帮助
 *
 *  编译（任选其一）：
 *      g++ -std=c++11 -O2 -o loc loc.cpp
 *      cl  /EHsc /O2 /Fe:loc.exe loc.cpp
 *
 *  说明：
 *      仅使用 C++11 标准库 + 操作系统目录 API，不依赖 <filesystem>，
 *      因此在 Dev-C++(TDM-GCC 4.9) / MinGW / MSVC / GCC / Clang 上均可编译。
 * ==========================================================================*/

#include <algorithm>
#include <cctype>
#include <cerrno>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <string>
#include <vector>

#ifdef _WIN32
#  include <windows.h>          // FindFirstFileA / FindNextFileA
#else
#  include <dirent.h>           // opendir / readdir / closedir
#  include <sys/stat.h>
#  include <sys/types.h>
#endif

/* ==========================================================================
 *  一、语言与扩展名定义
 * ==========================================================================*/

enum LangId
{
    LANG_C = 0,     /* C   */
    LANG_CPP,       /* C++ */
    LANG_JAVA,      /* Java*/
    LANG_PYTHON,    /* Python */
    LANG_COUNT
};

/* 表格中显示的语言名（顺序即输出顺序） */
static const char* const kLangName[LANG_COUNT] =
{
    "C", "C++", "Java", "Python"
};

/* 每种语言支持的扩展名，以 NULL 结尾
 * 注意：.h 归属 C（C++ 头文件请用 .hpp/.hh/.hxx）。
 *       如需调整归属，只改这张表即可。 */
static const char* const kLangExt[LANG_COUNT][12] =
{
    { "c", "h", NULL },                                                   /* C      */
    { "cpp", "cc", "cxx", "c++", "hpp", "hh", "hxx", "h++", "inl", NULL },/* C++    */
    { "java", NULL },                                                     /* Java   */
    { "py", "pyw", NULL }                                                 /* Python */
};

/* ==========================================================================
 *  二、统计结果
 * ==========================================================================*/

struct Stats
{
    long long files;    /* 文件个数     */
    long long functions;/* 函数 / 方法数 */
    long long blank;    /* 空行行数     */
    long long comment;  /* 注释行数     */
    long long code;     /* 代码行数     */

    Stats() : files(0), functions(0), blank(0), comment(0), code(0) {}

    void add(const Stats& o)
    {
        files   += o.files;
        functions += o.functions;
        blank   += o.blank;
        comment += o.comment;
        code    += o.code;
    }
};

/* ==========================================================================
 *  三、逐行扫描器
 * ==========================================================================*/

static bool isBlankLine(const std::string& s)
{
    for (std::size_t i = 0; i < s.size(); ++i)
        if (!std::isspace(static_cast<unsigned char>(s[i])))
            return false;
    return true;
}

/* 去掉 Windows 换行符残留的 '\r' */
static void chomp(std::string& s)
{
    if (!s.empty() && s[s.size() - 1] == '\r')
        s.erase(s.size() - 1);
}

static bool isIdentifierStart(char c)
{
    return std::isalpha(static_cast<unsigned char>(c)) || c == '_' || c == '$';
}

static bool isIdentifierPart(char c)
{
    return std::isalnum(static_cast<unsigned char>(c)) || c == '_' || c == '$';
}

/* 将 C 系代码行（已去掉注释和字符串内容）切成轻量 token。 */
static void appendTokens(const std::string& line, std::vector<std::string>& tokens)
{
    std::size_t i = 0;
    while (i < line.size())
    {
        const char c = line[i];
        if (std::isspace(static_cast<unsigned char>(c)))
        {
            ++i;
            continue;
        }
        if (isIdentifierStart(c) || std::isdigit(static_cast<unsigned char>(c)))
        {
            const std::size_t start = i++;
            while (i < line.size() && isIdentifierPart(line[i]))
                ++i;
            tokens.push_back(line.substr(start, i - start));
            continue;
        }
        tokens.push_back(line.substr(i, 1));
        ++i;
    }
}

static bool isControlOrQualifier(const std::string& name)
{
    static const char* const words[] = {
        "if", "for", "while", "switch", "catch", "synchronized", "foreach",
        "sizeof", "alignof", "decltype", "typeid", "static_assert", "requires",
        "noexcept", "throw", "new", "delete", "return", "else", "do"
    };
    for (std::size_t i = 0; i < sizeof(words) / sizeof(words[0]); ++i)
        if (name == words[i])
            return true;
    return false;
}

static bool isFunctionDeclarator(const std::vector<std::string>& tokens,
                                 std::size_t openParen)
{
    if (openParen == 0)
        return false;

    const std::string& before = tokens[openParen - 1];
    if (isIdentifierStart(before[0]))
    {
        if (isControlOrQualifier(before))
            return false;
        if (openParen >= 2)
        {
            const std::string& prefix = tokens[openParen - 2];
            if (prefix == "@" || prefix == "=" || prefix == ":" || prefix == ","
                || prefix == "." || prefix == "->" || prefix == "new")
            {
                /* public: C++ constructors are still declarations. */
                if (prefix != ":" || (openParen < 3
                    || (tokens[openParen - 3] != "public"
                        && tokens[openParen - 3] != "protected"
                        && tokens[openParen - 3] != "private")))
                    return false;
            }
        }
        return true;
    }

    /* operator overloads have punctuation or ')' immediately before params. */
    const std::size_t begin = openParen > 12 ? openParen - 12 : 0;
    for (std::size_t i = openParen; i > begin; )
    {
        --i;
        if (tokens[i] == "operator")
            return true;
        if (tokens[i] == ";" || tokens[i] == "{" || tokens[i] == "}")
            break;
    }
    return false;
}

static long long countCLikeFunctions(const std::vector<std::string>& tokens)
{
    const std::size_t n = tokens.size();
    std::vector<int> parenMate(n, -1), braceMate(n, -1);
    std::vector<std::size_t> stack;
    for (std::size_t i = 0; i < n; ++i)
    {
        if (tokens[i] == "(")
            stack.push_back(i);
        else if (tokens[i] == ")" && !stack.empty())
        {
            const std::size_t open = stack.back();
            stack.pop_back();
            parenMate[open] = static_cast<int>(i);
            parenMate[i] = static_cast<int>(open);
        }
    }
    stack.clear();
    for (std::size_t i = 0; i < n; ++i)
    {
        if (tokens[i] == "{")
            stack.push_back(i);
        else if (tokens[i] == "}" && !stack.empty())
        {
            const std::size_t open = stack.back();
            stack.pop_back();
            braceMate[open] = static_cast<int>(i);
            braceMate[i] = static_cast<int>(open);
        }
    }

    long long count = 0;
    for (std::size_t close = 0; close < n; ++close)
    {
        if (tokens[close] != ")" || parenMate[close] < 0)
            continue;
        const std::size_t open = static_cast<std::size_t>(parenMate[close]);
        if (!isFunctionDeclarator(tokens, open))
            continue;

        bool hasCtorInitializer = false;
        bool foundBody = false;
        std::size_t i = close + 1;
        while (i < n)
        {
            const std::string& token = tokens[i];
            if (token == "{")
            {
                /* Skip braced member initializers such as : value{1} { body }. */
                if (hasCtorInitializer && braceMate[i] >= 0
                    && static_cast<std::size_t>(braceMate[i] + 1) < n
                    && tokens[static_cast<std::size_t>(braceMate[i] + 1)] == ",")
                {
                    i = static_cast<std::size_t>(braceMate[i]) + 2;
                    continue;
                }
                if (hasCtorInitializer && braceMate[i] >= 0
                    && static_cast<std::size_t>(braceMate[i] + 1) < n
                    && tokens[static_cast<std::size_t>(braceMate[i] + 1)] == "{")
                {
                    i = static_cast<std::size_t>(braceMate[i]) + 1;
                    continue;
                }
                foundBody = true;
                break;
            }
            if (token == ";" || token == "=" || token == "}")
                break;                  /* 原型、= default / = 0 或不完整声明 */
            if (token == ":")
                hasCtorInitializer = true;
            if (token == "(")
            {
                const bool qualifierCall = i > 0
                    && (tokens[i - 1] == "noexcept" || tokens[i - 1] == "throw"
                        || tokens[i - 1] == "requires" || tokens[i - 1] == "decltype");
                if (!qualifierCall && !hasCtorInitializer)
                    break;
                if (parenMate[i] < 0)
                    break;
                i = static_cast<std::size_t>(parenMate[i]) + 1;
                continue;
            }
            if (token == ")")
                break;                  /* 例如 if (call()) 后面的控制块 */
            if (token == "," && !hasCtorInitializer)
                break;
            ++i;
        }
        if (foundBody)
            ++count;
    }
    return count;
}

/* --------------------------------------------------------------------------
 *  C / C++ / Java 扫描：支持行注释、块注释、字符串常量
 *
 *  判定规则（与主流工具 cloc 一致）：
 *     - 整行空白            -> blank
 *     - 该行含任意有效代码   -> code   （行尾注释算代码）
 *     - 该行只有注释        -> comment
 * ------------------------------------------------------------------------ */
static bool scanCLike(std::istream& in, Stats& st)
{
    std::string line;
    bool inBlock = false;               /* 是否正处于块注释之中 */
    std::vector<std::string> tokens;

    while (std::getline(in, line))
    {
        chomp(line);

        if (isBlankLine(line))          /* 空行（含块注释中的空行） */
        {
            ++st.blank;
            continue;
        }

        std::string codeLine(line.size(), ' ');
        bool hasCode  = false;
        std::size_t i = 0;
        const std::size_t n = line.size();

        while (i < n)
        {
            /* --- 块注释内部：寻找结束标记 --- */
            if (inBlock)
            {
                std::size_t e = line.find("*/", i);
                if (e == std::string::npos)
                    i = n;                          /* 整行仍在注释中 */
                else
                {
                    inBlock = false;                /* 块注释结束 */
                    i = e + 2;
                }
                continue;
            }

            const char c = line[i];

            /* --- // 行注释：本行剩余部分忽略 --- */
            if (c == '/' && i + 1 < n && line[i + 1] == '/')
                break;

            /* --- 块注释开始（斜杠 + 星号） --- */
            if (c == '/' && i + 1 < n && line[i + 1] == '*')
            {
                inBlock = true;
                i += 2;
                continue;
            }

            /* --- 字符串 / 字符常量：整体跳过，避免 "http://x" 被误判 --- */
            if (c == '"' || c == '\'')
            {
                const char quote = c;
                ++i;
                while (i < n)
                {
                    if (line[i] == '\\') { i += 2; continue; }
                    if (line[i] == quote) { ++i; break; }
                    ++i;
                }
                hasCode = true;
                continue;
            }

            if (!std::isspace(static_cast<unsigned char>(c)))
            {
                hasCode = true;
                codeLine[i] = c;
            }
            else
                codeLine[i] = c;

            ++i;
        }

        appendTokens(codeLine, tokens);

        if (hasCode)
            ++st.code;
        else
            ++st.comment;               /* 本行非空但无代码 -> 纯注释行 */
    }

    st.functions = countCLikeFunctions(tokens);
    return !inBlock;
}

/* --------------------------------------------------------------------------
 *  Python 扫描：支持  # 行注释、''' """ 三引号字符串（视为注释）
 *
 *  返回值：扫描结束时三引号是否已闭合（false 通常意味着扫描状态跑飞了）
 * ------------------------------------------------------------------------ */
static bool scanPython(std::istream& in, Stats& st)
{
    std::string line;
    std::string triple;                 /* 当前处于的三引号，空串表示不在其中 */

    while (std::getline(in, line))
    {
        chomp(line);

        if (isBlankLine(line))
        {
            ++st.blank;
            continue;
        }

        bool hasCode  = false;
        std::string codeLine(line.size(), ' ');
        std::size_t i = 0;
        const std::size_t n = line.size();

        while (i < n)
        {
            /* --- 三引号内部：找配对的结束三引号 --- */
            if (!triple.empty())
            {
                std::size_t e = line.find(triple, i);
                if (e == std::string::npos)
                    i = n;
                else
                {
                    i = e + 3;
                    triple.clear();
                }
                continue;
            }

            const char c = line[i];

            /* --- # 行注释 --- */
            if (c == '#')
                break;

            /* --- 三引号字符串开始 --- */
            if ((c == '"' || c == '\'') && i + 2 < n
                && line[i + 1] == c && line[i + 2] == c)
            {
                triple.assign(3, c);
                i += 3;
                continue;
            }

            /* --- 普通字符串：整体跳过 --- */
            if (c == '"' || c == '\'')
            {
                const char quote = c;
                ++i;
                while (i < n)
                {
                    if (line[i] == '\\') { i += 2; continue; }
                    if (line[i] == quote) { ++i; break; }
                    ++i;
                }
                hasCode = true;
                continue;
            }

            if (!std::isspace(static_cast<unsigned char>(c)))
            {
                hasCode = true;
                codeLine[i] = c;
            }
            else
                codeLine[i] = c;

            ++i;
        }

        /* Python 函数定义以语句形式出现在行首，可跨行书写参数列表。 */
        std::size_t p = 0;
        while (p < codeLine.size() && std::isspace(static_cast<unsigned char>(codeLine[p]))) ++p;
        if (codeLine.compare(p, 5, "async") == 0
            && (p + 5 == codeLine.size() || !isIdentifierPart(codeLine[p + 5])))
        {
            p += 5;
            while (p < codeLine.size() && std::isspace(static_cast<unsigned char>(codeLine[p]))) ++p;
        }
        if (codeLine.compare(p, 3, "def") == 0
            && (p + 3 == codeLine.size() || !isIdentifierPart(codeLine[p + 3])))
        {
            p += 3;
            while (p < codeLine.size() && std::isspace(static_cast<unsigned char>(codeLine[p]))) ++p;
            if (p < codeLine.size() && isIdentifierStart(codeLine[p]))
                ++st.functions;
        }

        if (hasCode)
            ++st.code;
        else
            ++st.comment;
    }

    return triple.empty();
}

/* ==========================================================================
 *  四、目录遍历（跨平台）
 * ==========================================================================*/

/* 需要跳过的目录名（版本控制 / 构建产物 / 依赖目录），可按需增删 */
static const char* const kSkipDirs[] =
{
    ".git", ".svn", ".hg", ".idea", ".vs", ".vscode",
    "node_modules", "obj", "Debug", "Release", "build", "dist"
};

static bool shouldSkipDir(const std::string& name)
{
    if (!name.empty() && name[0] == '.')        /* 以 . 开头的隐藏目录 */
        return true;
    for (std::size_t i = 0; i < sizeof(kSkipDirs) / sizeof(kSkipDirs[0]); ++i)
        if (name == kSkipDirs[i])
            return true;
    return false;
}

#ifdef _WIN32
static const char kSep = '\\';
#else
static const char kSep = '/';
#endif

/* 拼接目录与名字，保证不会出现重复分隔符。
 * 这一点在 Windows 上很关键：加了长路径前缀的路径不走系统规范化，
 * 一旦出现双反斜杠会直接报 ERROR_INVALID_NAME，导致整棵子树都读不到。 */
static std::string joinPath(const std::string& dir, const std::string& name)
{
    if (dir.empty())
        return name;

    const char last = dir[dir.size() - 1];
    if (last == '\\' || last == '/')
        return dir + name;

    return dir + kSep + name;
}

/* 列出目录内容：子目录放入 subDirs，普通文件放入 files */
#ifdef _WIN32
/* 把相对路径统一转成绝对路径 */
static bool getAbsolutePath(const std::string& in, std::string& out)
{
    char buf[MAX_PATH * 4];
    const DWORD n = ::GetFullPathNameA(in.c_str(), (DWORD)sizeof(buf), buf, NULL);
    if (n == 0 || n >= (DWORD)sizeof(buf))
        return false;
    out.assign(buf, n);
    return true;
}

/* 加上 \\?\ 前缀，突破 MAX_PATH(260 字符) 限制，
 * 这样整盘扫描时遇到的深层目录也能正常访问 */
static std::string toExtendedPath(const std::string& abs)
{
    if (abs.compare(0, 4, "\\\\?\\") == 0)
        return abs;
    if (abs.compare(0, 2, "\\\\") == 0)             /* UNC 网络路径 */
        return "\\\\?\\UNC\\" + abs.substr(2);
    return "\\\\?\\" + abs;
}

static bool listDirectory(const std::string& dir,
                          std::vector<std::string>& subDirs,
                          std::vector<std::string>& files)
{
    const std::string pattern = joinPath(dir, "*");

    WIN32_FIND_DATAA fd;
    HANDLE h = ::FindFirstFileA(pattern.c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE)
        return false;

    do
    {
        const std::string name = fd.cFileName;
        if (name == "." || name == "..")
            continue;

        const std::string full = joinPath(dir, name);

        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
        {
            /* 跳过符号链接 / junction，防止目录环导致死循环 */
            if (fd.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)
                continue;
            if (!shouldSkipDir(name))
                subDirs.push_back(full);
        }
        else
        {
            files.push_back(full);
        }
    } while (::FindNextFileA(h, &fd));

    ::FindClose(h);
    return true;
}
#else
static bool listDirectory(const std::string& dir,
                          std::vector<std::string>& subDirs,
                          std::vector<std::string>& files)
{
    DIR* d = ::opendir(dir.c_str());
    if (!d)
        return false;

    struct dirent* e;
    while ((e = ::readdir(d)) != NULL)
    {
        const std::string name = e->d_name;
        if (name == "." || name == "..")
            continue;

        const std::string full = joinPath(dir, name);

        struct stat sb;
        if (::lstat(full.c_str(), &sb) != 0)
            continue;
        if (S_ISLNK(sb.st_mode))            /* 跳过符号链接 */
            continue;

        if (S_ISDIR(sb.st_mode))
        {
            if (!shouldSkipDir(name))
                subDirs.push_back(full);
        }
        else if (S_ISREG(sb.st_mode))
        {
            files.push_back(full);
        }
    }

    ::closedir(d);
    return true;
}
#endif

/* 取小写扩展名（不含点）；没有扩展名返回空串 */
static std::string getExtension(const std::string& path)
{
    std::size_t slash = path.find_last_of("/\\");
    std::size_t dot   = path.find_last_of('.');
    if (dot == std::string::npos || (slash != std::string::npos && dot < slash))
        return std::string();

    std::string ext = path.substr(dot + 1);
    for (std::size_t i = 0; i < ext.size(); ++i)
        ext[i] = static_cast<char>(std::tolower(static_cast<unsigned char>(ext[i])));
    return ext;
}

/* ==========================================================================
 *  五、主流程
 * ==========================================================================*/

static void printUsage(const char* prog)
{
    std::cout
        << "代码行统计工具 (Lines of Code Counter)\n"
        << "\n"
        << "用法: " << prog << " [目录] [-s]\n"
        << "\n"
        << "  目录    要统计的目录，省略时默认为当前目录\n"
        << "  -s      简化模式，blank / comment 两列输出 \"/\"\n"
        << "  -h      显示本帮助\n"
        << "\n"
        << "支持语言: C (.c .h) | C++ (.cpp .cc .cxx .hpp .hh .hxx)\n"
        << "          Java (.java) | Python (.py .pyw)\n"
        << "函数数统计有函数体的定义（空函数体计数；不计原型和 lambda）。\n";
}

int main(int argc, char** argv)
{
    std::string root;
    bool simpleMode = false;

    /* ---------- 1. 解析命令行参数 ---------- */
    for (int i = 1; i < argc; ++i)
    {
        const std::string arg = argv[i];

        if (arg == "-h" || arg == "--help")
        {
            printUsage(argv[0]);
            return 0;
        }
        if (arg == "-s" || arg == "--simple")
        {
            simpleMode = true;
            continue;
        }
        if (!arg.empty() && arg[0] == '-' && arg != "-")
        {
            std::cerr << "未知选项: " << arg << " (使用 -h 查看帮助)\n";
            return 2;
        }

        if (!root.empty())
        {
            std::cerr << "参数过多: " << arg << " (只能指定一个目录)\n";
            return 2;
        }
        root = arg;
    }

    if (root.empty())
        root = ".";                     /* 未指定目录 -> 当前目录 */

    const std::string rootDisplay = root;   /* 保留用户原始写法，仅用于报错提示 */

#ifdef _WIN32
    /* 整盘扫描会碰到很深的目录，先转绝对路径再加 \\?\ 前缀 */
    {
        std::string absRoot;
        if (getAbsolutePath(root, absRoot))
            root = toExtendedPath(absRoot);
    }
#endif

    /* 先确认根目录可访问，避免路径写错时静默输出全 0 */
    {
        std::vector<std::string> probeDirs, probeFiles;
        if (!listDirectory(root, probeDirs, probeFiles))
        {
            std::cerr << "错误: 无法打开目录 \"" << rootDisplay
                      << "\"，请检查路径是否存在。\n";
            return 1;
        }
    }

    /* ---------- 2. 建扩展名 -> 语言 的索引 ---------- */
    std::map<std::string, int> extToLang;
    for (int l = 0; l < LANG_COUNT; ++l)
        for (int k = 0; kLangExt[l][k] != NULL; ++k)
            extToLang[kLangExt[l][k]] = l;

    /* ---------- 3. 遍历目录，统计各类文件 ---------- */
    Stats perLang[LANG_COUNT];
    Stats total;
    long long skippedFiles = 0;
    long long unterminated = 0;         /* 结束时仍处于注释状态的文件数 */

    std::vector<std::string> pending;
    pending.push_back(root);

    std::vector<std::string> subDirs, files;

    /* 安全上限：纯属异常情况下的兜底，正常运行不会触发 */
    const std::size_t kMaxDirs = 20000000;
    std::size_t visitedDirs = 0;
    bool limitHit = false;

    while (!pending.empty())
    {
        if (visitedDirs >= kMaxDirs)
        {
            limitHit = true;
            break;
        }

        const std::string dir = pending.back();
        pending.pop_back();
        ++visitedDirs;

        subDirs.clear();
        files.clear();
        if (!listDirectory(dir, subDirs, files))
            continue;                   /* 无权限等情况直接跳过 */

        for (std::size_t i = 0; i < subDirs.size(); ++i)
            pending.push_back(subDirs[i]);

        for (std::size_t i = 0; i < files.size(); ++i)
        {
            const std::string& path = files[i];

            const std::string ext = getExtension(path);
            if (ext.empty())
                continue;               /* 无扩展名，不统计 */

            std::map<std::string, int>::const_iterator it = extToLang.find(ext);
            if (it == extToLang.end())
                continue;               /* 不在支持列表内，不统计 */

            const int lang = it->second;

            std::ifstream fin(path.c_str(), std::ios::in | std::ios::binary);
            if (!fin)
            {
                ++skippedFiles;         /* 打不开的文件 */
                continue;
            }

            Stats st;
            st.files = 1;

            const bool closed =
                (lang == LANG_PYTHON) ? scanPython(fin, st) : scanCLike(fin, st);
            if (!closed)
                ++unterminated;

            fin.close();

            perLang[lang].add(st);
            total.add(st);
        }
    }

    /* ---------- 4. 输出统计表格 ---------- */
    const int W_LANG = 15;              /* 语言列宽 */
    const int W_NUM  = 12;              /* 数字列宽 */
    const std::string sep(W_LANG + W_NUM * 5, '-');

    std::cout << sep << "\n";
    std::cout << std::left  << std::setw(W_LANG) << "Language"
              << std::right << std::setw(W_NUM)  << "files"
                            << std::setw(W_NUM)  << "functions"
                            << std::setw(W_NUM)  << "blank"
                            << std::setw(W_NUM)  << "comment"
                            << std::setw(W_NUM)  << "code" << "\n";
    std::cout << sep << "\n";

    for (int l = 0; l < LANG_COUNT; ++l)
    {
        const Stats& s = perLang[l];

        std::cout << std::left  << std::setw(W_LANG) << kLangName[l]
                  << std::right << std::setw(W_NUM)  << s.files
                                << std::setw(W_NUM)  << s.functions;

        if (simpleMode)                 /* 简化模式：blank / comment 显示 "/" */
            std::cout << std::setw(W_NUM) << "/"
                      << std::setw(W_NUM) << "/";
        else
            std::cout << std::setw(W_NUM) << s.blank
                      << std::setw(W_NUM) << s.comment;

        std::cout << std::setw(W_NUM) << s.code << "\n";
    }

    std::cout << sep << "\n";
    std::cout << std::left  << std::setw(W_LANG) << "SUM"
              << std::right << std::setw(W_NUM)  << total.files
                            << std::setw(W_NUM)  << total.functions;

    if (simpleMode)
        std::cout << std::setw(W_NUM) << "/"
                  << std::setw(W_NUM) << "/";
    else
        std::cout << std::setw(W_NUM) << total.blank
                  << std::setw(W_NUM) << total.comment;

    std::cout << std::setw(W_NUM) << total.code << "\n";
    std::cout << sep << "\n";

    if (limitHit)
        std::cerr << "[warn] 目录数量达到上限 " << kMaxDirs
                  << "，统计结果可能不完整。\n";

    if (unterminated > 0)
        std::cerr << "[warn] " << unterminated
                  << " 个文件扫描结束时注释状态未闭合，这些文件的统计可能不准。\n";

    if (skippedFiles > 0)
        std::cerr << "[warn] " << skippedFiles << " 个文件无法打开，已跳过。\n";

    return 0;
}
