#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <vector>
#include <cmath>
#include <string>
#include <algorithm>
#include <tuple>

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

    float cosine_similarity(const std::vector<float>& A, const std::vector<float>& B) {
        if (A.size() != B.size()) return 0.0f;
        float dot = 0.0f, denom_a = 0.0f, denom_b = 0.0f;
        for (size_t i = 0; i < A.size(); ++i) {
            dot += A[i] * B[i];
            denom_a += A[i] * A[i];
            denom_b += B[i] * B[i];
        }
        return dot / (std::sqrt(denom_a) * std::sqrt(denom_b) + 1e-9f);
    }

public:
    TodoEngine() {}

    void add_todo(int id, long long timestamp, const std::string& content, const std::vector<float>& vec) {
        database.push_back({id, timestamp, content, vec});
    }

    //search todos by time range and vector similarity
    std::vector<std::tuple<int, float, std::string>> search(
        long long start_ts, long long end_ts, const std::vector<float>& query_vec, int top_k
    ) {
        std::vector<std::tuple<int, float, std::string>> candidates;

        for (const auto& item : database) {
            if (item.timestamp >= start_ts && item.timestamp <= end_ts) {
                float score = cosine_similarity(query_vec, item.vector);
                // push tuple of (id, score, content)
                candidates.push_back(std::make_tuple(item.id, score, item.content));
            }
        }

        //sort logic
        std::sort(candidates.begin(), candidates.end(), 
            [](const std::tuple<int, float, std::string>& a, const std::tuple<int, float, std::string>& b) {
                return std::get<1>(a) > std::get<1>(b);
            });

        if (candidates.size() > top_k) candidates.resize(top_k);

        return candidates;
    }
    
    int size() { return database.size(); }
};

PYBIND11_MODULE(todo_core, m) {
    py::class_<TodoEngine>(m, "TodoEngine")
        .def(py::init<>())
        .def("add_todo", &TodoEngine::add_todo)
        .def("search", &TodoEngine::search)
        .def("size", &TodoEngine::size);
}