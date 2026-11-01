// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
namespace Common {inline void SetCurrentThreadName(const char*){}inline void SetCurrentThreadPriority(int){}inline void SetCurrentThreadToPerformanceCores(){}namespace ThreadPriority{constexpr int Critical=1;}}
