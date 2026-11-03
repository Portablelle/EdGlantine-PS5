"""Real RemovePendingShaders equivalence and membership work bound; dedie only."""
from pathlib import Path
import platform
import subprocess
import tempfile

assert platform.system() == 'Linux', 'Compile on dedie'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
text = (source / 'video_core/shader_cache.cpp').read_text()
start = text.index('void ShaderCache::RemovePendingShaders()')
end = text.index('{', start) + 1
depth = 1
while depth:
    depth += (text[end] == '{') - (text[end] == '}')
    end += 1
method = text[start:end]

cpp = r'''
#include <algorithm>
#include <cassert>
#include <compare>
#include <cstdio>
#include <functional>
#include <iterator>
#include <memory>
#include <mutex>
#include <random>
#include <unordered_map>
#include <vector>
#define ASSERT assert

// Count reads of the auxiliary membership list without changing pointer semantics
// or replacing any algorithms in the extracted production method.
size_t membership_reads = 0;
template<class T> struct CountingIterator {
    using value_type = T;
    using difference_type = std::ptrdiff_t;
    using iterator_category = std::random_access_iterator_tag;
    T* p{};
    T& operator*() const { ++membership_reads; return *p; }
    T& operator[](difference_type n) const { return *(*this + n); }
    CountingIterator& operator++() { ++p; return *this; }
    CountingIterator operator++(int) { auto old = *this; ++*this; return old; }
    CountingIterator& operator--() { --p; return *this; }
    CountingIterator operator--(int) { auto old = *this; --*this; return old; }
    CountingIterator& operator+=(difference_type n) { p += n; return *this; }
    CountingIterator& operator-=(difference_type n) { p -= n; return *this; }
    friend CountingIterator operator+(CountingIterator i, difference_type n) { return i += n; }
    friend CountingIterator operator+(difference_type n, CountingIterator i) { return i += n; }
    friend CountingIterator operator-(CountingIterator i, difference_type n) { return i -= n; }
    friend difference_type operator-(CountingIterator a, CountingIterator b) { return a.p - b.p; }
    auto operator<=>(const CountingIterator&) const = default;
};
namespace boost::container {
template<class T, size_t N> struct small_vector : std::vector<T> {
    CountingIterator<T> begin() { return {this->data()}; }
    CountingIterator<T> end() { return {this->data() + this->size()}; }
};
}
struct ShaderInfo { size_t id; };
struct ShaderCache {
    struct Entry { size_t addr_start; ShaderInfo* data; };
    struct Lookup : std::unordered_map<size_t, std::unique_ptr<Entry>> {
        std::vector<size_t> erased;
        void erase(iterator it) {
            erased.push_back(it->first);
            std::unordered_map<size_t, std::unique_ptr<Entry>>::erase(it);
        }
    } lookup_cache;
    std::mutex lookup_mutex;
    std::vector<Entry*> marked_for_removal;
    std::vector<std::unique_ptr<ShaderInfo>> storage;
    void RemovePendingShaders();
};
''' + method + r'''
void Check(size_t batch) {
    ShaderCache cache;
    const size_t count = 2 * batch + 31;
    for (size_t id = 0; id < count; ++id) {
        auto shader = std::make_unique<ShaderInfo>(ShaderInfo{id});
        cache.lookup_cache.emplace(id, std::make_unique<ShaderCache::Entry>(
                                          ShaderCache::Entry{id, shader.get()}));
        cache.storage.push_back(std::move(shader));
    }
    std::mt19937 random(1234);
    std::shuffle(cache.storage.begin(), cache.storage.end(), random);
    std::vector<ShaderInfo*> survivors;
    for (const auto& shader : cache.storage) {
        if (shader->id >= batch) survivors.push_back(shader.get());
    }
    for (size_t id = 0; id < batch; ++id) {
        auto* entry = cache.lookup_cache.at(id).get();
        cache.marked_for_removal.push_back(entry);
        cache.marked_for_removal.push_back(entry); // Repeated page invalidation.
    }
    std::shuffle(cache.marked_for_removal.begin(), cache.marked_for_removal.end(), random);
    membership_reads = 0;
    cache.RemovePendingShaders();
    const size_t reads = membership_reads;
    assert(cache.marked_for_removal.empty());
    assert(cache.storage.size() == survivors.size());
    for (size_t i = 0; i < survivors.size(); ++i) {
        assert(cache.storage[i].get() == survivors[i]); // Identity AND original order.
    }
    assert(cache.lookup_cache.size() == count - batch);
    for (size_t id = 0; id < count; ++id) {
        assert(cache.lookup_cache.contains(id) == (id >= batch));
    }
    const auto erased_before = cache.lookup_cache.erased;
    auto erased = erased_before;
    std::sort(erased.begin(), erased.end());
    assert(erased.size() == batch);
    for (size_t id = 0; id < batch; ++id) assert(erased[id] == id);
    if (batch <= 16) {
        // Linear membership reads each removed pointer once through its position
        // and the entire list for every survivor; no sorting of the small list.
        assert(reads == (count - batch) * batch + batch * (batch + 1) / 2);
    }
    if (batch == 1000) {
        // Old linear scan needs 1,531,500 reads; sort + binary search is far below
        // this loose bound, independent of pointer allocation/storage order.
        assert(reads < 200000 && "large removal batch must avoid quadratic membership reads");
    }
    cache.RemovePendingShaders(); // Empty repeat must not erase or scan again.
    assert(membership_reads == reads && cache.lookup_cache.erased == erased_before);
    std::printf("PASS batch=%zu: survivors/order/lookup erasures, membership reads=%zu\n", batch, reads);
}
int main() {
    for (size_t batch : {0, 1, 16, 17, 1000}) Check(batch);
}
'''

with tempfile.TemporaryDirectory(prefix='sorted-shader-removal-') as tmp:
    path = Path(tmp)
    cpp_path = path / 'check.cpp'
    cpp_path.write_text(cpp)
    exe = path / 'check'
    subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(cpp_path), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
