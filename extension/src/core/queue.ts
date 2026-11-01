export type QueueItemStatus = "queued" | "processing" | "completed" | "failed";

export interface QueueTaskResult<T> {
  skippedDuplicate: boolean;
  value?: T;
}

/**
 * Hàng đợi xử lý trang truyện tuần tự (mặc định `concurrency = 1`),
 * ngăn chặn việc gửi dịch trùng lặp cùng một ảnh khi ảnh đang trong hàng đợi,
 * đang dịch hoặc đã dịch thành công.
 */
export class SequentialPageQueue<T = unknown> {
  private readonly concurrency: number;
  private activeCount = 0;
  private readonly statusMap = new Map<string, QueueItemStatus>();
  private readonly resultCache = new Map<string, T>();
  private readonly pendingQueue: Array<{
    pageKey: string;
    task: () => Promise<T>;
    resolve: (res: QueueTaskResult<T>) => void;
    reject: (err: unknown) => void;
  }> = [];

  constructor(concurrency = 1) {
    this.concurrency = Math.max(1, concurrency);
  }

  public getStatus(pageKey: string): QueueItemStatus | undefined {
    return this.statusMap.get(pageKey);
  }

  public isBusyOrDone(pageKey: string): boolean {
    const st = this.statusMap.get(pageKey);
    return st === "queued" || st === "processing" || st === "completed";
  }

  public resetKey(pageKey: string): void {
    this.statusMap.delete(pageKey);
    this.resultCache.delete(pageKey);
  }

  public enqueue(
    pageKey: string,
    task: () => Promise<T>,
    force = false
  ): Promise<QueueTaskResult<T>> {
    const key = pageKey.trim();
    if (!force && this.isBusyOrDone(key)) {
      return Promise.resolve({
        skippedDuplicate: true,
        value: this.resultCache.get(key),
      });
    }

    this.statusMap.set(key, "queued");

    return new Promise<QueueTaskResult<T>>((resolve, reject) => {
      this.pendingQueue.push({ pageKey: key, task, resolve, reject });
      this.pump();
    });
  }

  private pump(): void {
    while (this.activeCount < this.concurrency && this.pendingQueue.length > 0) {
      const nextItem = this.pendingQueue.shift()!;
      this.activeCount += 1;
      this.statusMap.set(nextItem.pageKey, "processing");

      Promise.resolve()
        .then(() => nextItem.task())
        .then((val) => {
          this.statusMap.set(nextItem.pageKey, "completed");
          this.resultCache.set(nextItem.pageKey, val);
          nextItem.resolve({ skippedDuplicate: false, value: val });
        })
        .catch((err) => {
          this.statusMap.set(nextItem.pageKey, "failed");
          nextItem.reject(err);
        })
        .finally(() => {
          this.activeCount -= 1;
          this.pump();
        });
    }
  }
}
