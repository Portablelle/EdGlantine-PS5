// SPDX-License-Identifier: GPL-3.0-or-later
#include "update_notice.h"
namespace Eden::UpdateNotice {
void Start() {}
bool Take(Offer*) { return false; }
bool Begin() { return false; }
Progress Poll() { return {}; }
void Cancel() {}
bool Apply() { return false; }
void Finish() {}
}
