# ==========================================================
#  代码行统计工具 (loc) -- Makefile
#  用法:  make        # 编译
#         make clean  # 清理
# ==========================================================

CXX      ?= g++
CXXFLAGS ?= -std=c++11 -O2 -Wall -Wextra

TARGET = loc
SRC    = loc.cpp

# Windows 下生成 .exe
ifeq ($(OS),Windows_NT)
TARGET := loc.exe
endif

all: $(TARGET)

$(TARGET): $(SRC)
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -f loc loc.exe

.PHONY: all clean
