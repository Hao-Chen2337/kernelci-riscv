# src/sketch/ —— 所有者最初的手写草稿

这里是最初那几份设计草稿（`kbuild` / `build` / `kjob` / `job` / `out` / `poller` /
`gui` / `drift` / `re`，加上 `run_latest` / `pull_worker` / `runday's` 三个入口），
**一字未改**，留作对照。

它们不是可运行的代码（没有扩展名，是草稿），实现是仓库根的 `lib/*.py`。
每个 `lib/*.py` 的模块 docstring 第一节就是对应草稿的原文，所以读代码时能看到
"当初想的是什么"和"最后长成什么样"的差别。接口的正式版本在 `include/kci/*.hpp`。
