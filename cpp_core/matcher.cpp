#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <algorithm>
#include <cmath>
#include <string>
#include <tuple>
#include <vector>

namespace py = pybind11;

struct TodoItem {
    int id;
    long long timestamp;
    std::string content;
    std::vector<float> vector;
};

class TodoEngine {
private:
    std::vector<TodoItem> database;

    float cosine_similarity(
        const std::vector<float>& a,
        const std::vector<float>& b
    ) const {
        if (a.size() != b.size() || a.empty()) {
            return 0.0f;
        }

        float dot = 0.0f;
        float norm_a = 0.0f;
        float norm_b = 0.0f;

        for (std::size_t i = 0; i < a.size(); ++i) {
            dot += a[i] * b[i];
            norm_a += a[i] * a[i];
            norm_b += b[i] * b[i];
        }

        const float denominator =
            std::sqrt(norm_a) * std::sqrt(norm_b);

        if (denominator <= 1e-9f) {
            return 0.0f;
        }

        return dot / denominator;
    }

public:
    TodoEngine() = default;

    bool upsert_todo(
        int id,
        long long timestamp,
        const std::string& content,
        const std::vector<float>& vec
    ) {
        auto iterator = std::find_if(
            database.begin(),
            database.end(),
            [id](const TodoItem& item) {
                return item.id == id;
            }
        );

        TodoItem new_item{id, timestamp, content, vec};

        if (iterator != database.end()) {
            *iterator = std::move(new_item);
            return false;  // existing item updated
        }

        database.push_back(std::move(new_item));
        return true;  // new item inserted
    }

    // 保留旧 API 名称，但内部使用 upsert，避免同 ID 重复。
    void add_todo(
        int id,
        long long timestamp,
        const std::string& content,
        const std::vector<float>& vec
    ) {
        upsert_todo(id, timestamp, content, vec);
    }

    bool remove_todo(int id) {
        const auto old_size = database.size();

        database.erase(
            std::remove_if(
                database.begin(),
                database.end(),
                [id](const TodoItem& item) {
                    return item.id == id;
                }
            ),
            database.end()
        );

        return database.size() < old_size;
    }

    void clear() {
        database.clear();
    }

    std::vector<std::tuple<int, float, std::string>> search(
        long long start_ts,
        long long end_ts,
        const std::vector<float>& query_vec,
        int top_k
    ) const {
        std::vector<std::tuple<int, float, std::string>> candidates;

        if (top_k <= 0) {
            return candidates;
        }

        candidates.reserve(database.size());

        for (const auto& item : database) {
            if (
                item.timestamp >= start_ts
                && item.timestamp <= end_ts
            ) {
                const float score = cosine_similarity(
                    query_vec,
                    item.vector
                );

                candidates.emplace_back(
                    item.id,
                    score,
                    item.content
                );
            }
        }

        std::sort(
            candidates.begin(),
            candidates.end(),
            [](
                const std::tuple<int, float, std::string>& left,
                const std::tuple<int, float, std::string>& right
            ) {
                return std::get<1>(left) > std::get<1>(right);
            }
        );

        if (
            candidates.size()
            > static_cast<std::size_t>(top_k)
        ) {
            candidates.resize(
                static_cast<std::size_t>(top_k)
            );
        }

        return candidates;
    }

    int size() const {
        return static_cast<int>(database.size());
    }
};

PYBIND11_MODULE(todo_core, module) {
    py::class_<TodoEngine>(module, "TodoEngine")
        .def(py::init<>())
        .def("add_todo", &TodoEngine::add_todo)
        .def("upsert_todo", &TodoEngine::upsert_todo)
        .def("remove_todo", &TodoEngine::remove_todo)
        .def("clear", &TodoEngine::clear)
        .def("search", &TodoEngine::search)
        .def("size", &TodoEngine::size);
}
