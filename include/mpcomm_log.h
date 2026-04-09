// Copyright 2024 KVCache.AI
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#ifndef MPCOMM_LOG_H_
#define MPCOMM_LOG_H_

#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <pthread.h>

namespace mpcomm {

// =====================================================================
// Log levels — controlled at runtime via MPCOMM_LOG_LEVEL env var.
//
//   0 = ERROR only  (minimal output)
//   1 = WARN + ERROR
//   2 = INFO + WARN + ERROR  (default)
//   3 = DEBUG + INFO + WARN + ERROR  (verbose, includes transfer stats)
//
// Environment variable: MPCOMM_LOG_LEVEL
//   "0" or "error"   -> ERROR only
//   "1" or "warn"    -> WARN + ERROR
//   "2" or "info"    -> INFO + WARN + ERROR  (default)
//   "3" or "debug"   -> DEBUG + all above (transfer timing/NIC stats)
// =====================================================================

enum MPCommLogLevel {
    MPCOMM_LOG_LEVEL_ERROR = 0,
    MPCOMM_LOG_LEVEL_WARN  = 1,
    MPCOMM_LOG_LEVEL_INFO  = 2,
    MPCOMM_LOG_LEVEL_DEBUG = 3,
};

// Singleton log level holder — initialized once from environment variable.
// Thread-safe via static initialization (C++11 guarantees).
inline int mpcomm_get_log_level() {
    static int level = []() {
        int default_level = MPCOMM_LOG_LEVEL_INFO;
        const char* env = std::getenv("MPCOMM_LOG_LEVEL");
        if (!env || env[0] == '\0') return default_level;
        // Accept numeric or string values
        if (strcmp(env, "0") == 0 || strcmp(env, "error") == 0 || strcmp(env, "ERROR") == 0)
            return (int)MPCOMM_LOG_LEVEL_ERROR;
        if (strcmp(env, "1") == 0 || strcmp(env, "warn") == 0 || strcmp(env, "WARN") == 0)
            return (int)MPCOMM_LOG_LEVEL_WARN;
        if (strcmp(env, "2") == 0 || strcmp(env, "info") == 0 || strcmp(env, "INFO") == 0)
            return (int)MPCOMM_LOG_LEVEL_INFO;
        if (strcmp(env, "3") == 0 || strcmp(env, "debug") == 0 || strcmp(env, "DEBUG") == 0)
            return (int)MPCOMM_LOG_LEVEL_DEBUG;
        return default_level;
    }();
    return level;
}

// Get current timestamp as "HH:MM:SS.mmm" (millisecond precision)
inline void mpcomm_log_timestamp(char* buf, size_t len) {
    auto now = std::chrono::system_clock::now();
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        now.time_since_epoch()) % 1000;
    std::time_t t = std::chrono::system_clock::to_time_t(now);
    struct tm tm_buf;
    localtime_r(&t, &tm_buf);
    snprintf(buf, len, "%02d:%02d:%02d.%03d",
             tm_buf.tm_hour, tm_buf.tm_min, tm_buf.tm_sec,
             (int)ms.count());
}

// Get lightweight thread ID (low 16 bits of pthread_self, avoids gettid syscall)
inline unsigned int mpcomm_log_tid() {
    return (unsigned int)((uintptr_t)pthread_self() & 0xFFFF);
}

// =====================================================================
// Core logging macros
//
// Format: [LEVEL] HH:MM:SS.mmm [tid] file:line | message
//
// MPCOMM_LOG_DEBUG(fmt, ...)  — DEBUG level, stdout (transfer stats, timing)
// MPCOMM_LOG_INFO(fmt, ...)   — INFO level, stdout
// MPCOMM_LOG_WARN(fmt, ...)   — WARN level, stderr
// MPCOMM_LOG_ERROR(fmt, ...)  — ERROR level, stderr (always printed)
// MPCOMM_PLOG_ERROR(fmt, ...) — ERROR level with errno, stderr (always printed)
// =====================================================================

// Extract short filename from __FILE__ (strip directory path)
#define MPCOMM_LOG_FILENAME_ \
    (strrchr(__FILE__, '/') ? strrchr(__FILE__, '/') + 1 : __FILE__)

#define MPCOMM_LOG_IMPL_(level_str, fp, fmt, ...) \
    do { \
        char ts_buf_[16]; \
        mpcomm::mpcomm_log_timestamp(ts_buf_, sizeof(ts_buf_)); \
        fprintf(fp, "[%s] %s [%04x] %s:%d | " fmt, \
                level_str, ts_buf_, mpcomm::mpcomm_log_tid(), \
                MPCOMM_LOG_FILENAME_, __LINE__, ##__VA_ARGS__); \
    } while (0)

#define MPCOMM_LOG_DEBUG(fmt, ...) \
    do { \
        if (mpcomm::mpcomm_get_log_level() >= mpcomm::MPCOMM_LOG_LEVEL_DEBUG) { \
            MPCOMM_LOG_IMPL_("DEBUG", stdout, fmt, ##__VA_ARGS__); \
        } \
    } while (0)

#define MPCOMM_LOG_INFO(fmt, ...) \
    do { \
        if (mpcomm::mpcomm_get_log_level() >= mpcomm::MPCOMM_LOG_LEVEL_INFO) { \
            MPCOMM_LOG_IMPL_("INFO", stdout, fmt, ##__VA_ARGS__); \
        } \
    } while (0)

#define MPCOMM_LOG_WARN(fmt, ...) \
    do { \
        if (mpcomm::mpcomm_get_log_level() >= mpcomm::MPCOMM_LOG_LEVEL_WARN) { \
            MPCOMM_LOG_IMPL_("WARN", stderr, fmt, ##__VA_ARGS__); \
        } \
    } while (0)

#define MPCOMM_LOG_ERROR(fmt, ...) \
    do { \
        MPCOMM_LOG_IMPL_("ERROR", stderr, fmt, ##__VA_ARGS__); \
    } while (0)

// PLOG variant: appends errno description (replaces perror())
#define MPCOMM_PLOG_ERROR(fmt, ...) \
    do { \
        int saved_errno_ = errno; \
        MPCOMM_LOG_IMPL_("ERROR", stderr, fmt ": %s (errno=%d)\n", \
                          ##__VA_ARGS__, strerror(saved_errno_), saved_errno_); \
    } while (0)

}  // namespace mpcomm

#endif  // MPCOMM_LOG_H_
