package com.k3n.everifier.util;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.*;
import java.util.stream.Collectors;

public class ParallelPortChecker {

    private static final Logger logger = LoggerFactory.getLogger(ParallelPortChecker.class);

    private final int[] ports;
    private final ParallelPortCheckTask task;
    private static final int THREAD_POOL_SIZE = 5;  // max number of threads

    public interface ParallelPortCheckTask {
        SmtpRcptValidator.ValidationResult validatePort(int port) throws Exception;
    }

    public ParallelPortChecker(int[] ports, ParallelPortCheckTask task) {
        this.ports = ports;
        this.task = task;
        logger.debug("[Init] ParallelPortChecker initialized with ports: {}", Arrays.toString(ports));
    }

    public SmtpRcptValidator.ValidationResult checkAllPorts() throws InterruptedException {
        logger.info("[Start] Starting parallel port checks for ports: {}", Arrays.toString(ports));

        // Limit thread pool size max to THREAD_POOL_SIZE for resource control
        ExecutorService executor = Executors.newFixedThreadPool(Math.min(ports.length, THREAD_POOL_SIZE));

        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            logger.warn("[ShutdownHook] JVM shutdown triggered - shutting down executor");
            executor.shutdown();
        }));

        List<Future<SmtpRcptValidator.ValidationResult>> futures = Arrays.stream(ports)
                .mapToObj(port -> executor.submit(() -> {
                    String threadName = Thread.currentThread().getName();
                    logger.trace("[{}] Validating port {}...", threadName, port);
                    try {
                        SmtpRcptValidator.ValidationResult result = task.validatePort(port);
                        logger.debug("[{}] Port {} validation completed with status {}", threadName, port, result.getStatus());
                        return result;
                    } catch (Exception e) {
                        logger.warn("[{}] Port {} validation failed: {}", threadName, port, e.getMessage());
                        return new SmtpRcptValidator.ValidationResult(
                                SmtpRcptValidator.SmtpRecipientStatus.UnknownFailure,
                                -1, e.getMessage(),
                                "Port validation failed", null, "",
                                LocalDateTime.now().toString(),
                                "PortFailed", false, port, false);
                    }
                })).collect(Collectors.toList());

        SmtpRcptValidator.ValidationResult validResult = null;

        for (Future<SmtpRcptValidator.ValidationResult> future : futures) {
            try {
                // Wait max 15 seconds for each port validation
                SmtpRcptValidator.ValidationResult res = future.get(15, TimeUnit.SECONDS);
                logger.trace("[Future] Received result for port {}: {}", res.getPortUsed(), res.getStatus());
                if (res.getStatus() == SmtpRcptValidator.SmtpRecipientStatus.Valid) {
                    logger.info("[Success] Valid email found on port {}", res.getPortUsed());
                    validResult = res;
                    break;
                }
            } catch (TimeoutException e) {
                logger.warn("[Timeout] Port validation timed out: {}", e.getMessage());
            } catch (ExecutionException e) {
                logger.error("[ExecutionError] Exception during port validation result retrieval", e.getCause());
            } catch (InterruptedException e) {
                logger.error("[Interrupted] Thread interrupted while waiting for port validation", e);
                Thread.currentThread().interrupt();
                throw e;
            }
        }

        // Cancel unfinished tasks once a valid result is found or after processing all futures
        futures.forEach(future -> {
            if (!future.isDone()) {
                logger.trace("[Cancel] Canceling incomplete validation task");
                future.cancel(true);
            }
        });

        executor.shutdownNow();
        logger.debug("[Executor] Executor service shutdown initiated");

        if (validResult != null) {
            logger.debug("[Result] Returning first valid result");
            return validResult;
        }

        // If no valid result, return first available failed completed task
        for (Future<SmtpRcptValidator.ValidationResult> future : futures) {
            if (future.isDone() && !future.isCancelled()) {
                try {
                    SmtpRcptValidator.ValidationResult res = future.get();
                    logger.debug("[Result] Returning failed port validation result with status {} on port {}", res.getStatus(), res.getPortUsed());
                    return res;
                } catch (Exception e) {
                    logger.warn("[ResultRetrievalError] Unable to retrieve failed validation result: {}", e.getMessage());
                }
            }
        }

        logger.warn("[Fail] All ports failed validation");
        return new SmtpRcptValidator.ValidationResult(
                SmtpRcptValidator.SmtpRecipientStatus.UnknownFailure,
                -1, "All ports failed",
                "No successful validation", null, "",
                LocalDateTime.now().toString(),
                "AllPortsFailed", false, -1, false);
    }
}
