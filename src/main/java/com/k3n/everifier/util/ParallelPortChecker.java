package com.k3n.everifier.util;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Arrays;
import java.util.List;
import java.util.concurrent.*;
import java.util.stream.Collectors;

public class ParallelPortChecker {

    private static final Logger logger = LoggerFactory.getLogger(ParallelPortChecker.class);

    private final int[] ports;
    private final ParallelPortCheckTask task;

    public interface ParallelPortCheckTask {
        SmtpRcptValidator.ValidationResult validatePort(int port) throws Exception;
    }

    public ParallelPortChecker(int[] ports, ParallelPortCheckTask task) {
        this.ports = ports;
        this.task = task;
        logger.debug("ParallelPortChecker initialized with ports: {}", arrayToString(ports));
    }

    public SmtpRcptValidator.ValidationResult checkAllPorts() throws InterruptedException {
        logger.debug("Starting parallel port checks...");

        ExecutorService executor = Executors.newFixedThreadPool(ports.length);

        Runtime.getRuntime().addShutdownHook(new Thread(new Runnable() {
            @Override
            public void run() {
                logger.debug("JVM shutdown hook triggered, shutting down executor");
                executor.shutdown();
            }
        }));

        List<Future<SmtpRcptValidator.ValidationResult>> futures = Arrays.stream(ports)
                .mapToObj(new java.util.function.IntFunction<Future<SmtpRcptValidator.ValidationResult>>() {
                    @Override
                    public Future<SmtpRcptValidator.ValidationResult> apply(final int port) {
                        return executor.submit(new Callable<SmtpRcptValidator.ValidationResult>() {
                            @Override
                            public SmtpRcptValidator.ValidationResult call() throws Exception {
                                logger.debug("Starting validation on port {}", port);
                                try {
                                    SmtpRcptValidator.ValidationResult result = task.validatePort(port);
                                    logger.debug("Validation on port {} completed with status {}", port, result.getStatus());
                                    return result;
                                } catch (Exception e) {
                                    logger.warn("Validation on port {} failed: {}", port, e.getMessage());
                                    return new SmtpRcptValidator.ValidationResult(
                                            SmtpRcptValidator.SmtpRecipientStatus.UnknownFailure,
                                            -1, e.getMessage(),
                                            "Port validation failed", null, "",
                                            java.time.LocalDateTime.now().toString(),
                                            "PortFailed", false, port, false);
                                }
                            }
                        });
                    }
                }).collect(Collectors.toList());

        SmtpRcptValidator.ValidationResult validResult = null;
        for (Future<SmtpRcptValidator.ValidationResult> future : futures) {
            try {
                SmtpRcptValidator.ValidationResult res = future.get();
                logger.debug("Received validation result with status {} on port {}", res.getStatus(), res.getPortUsed());
                if (res.getStatus() == SmtpRcptValidator.SmtpRecipientStatus.Valid) {
                    logger.info("Valid email found on port {}", res.getPortUsed());
                    validResult = res;
                    break;
                }
            } catch (Exception e) {
                logger.warn("Exception while waiting for port validation future: {}", e.getMessage());
            }
        }

        for (Future<SmtpRcptValidator.ValidationResult> future : futures) {
            if (!future.isDone()) {
                logger.debug("Cancelling port validation task on future");
                future.cancel(true);
            }
        }

        executor.shutdownNow();
        logger.debug("Executor shutdown initiated");

        if (validResult != null) {
            logger.debug("Returning first valid result from parallel port checks");
            return validResult;
        }

        for (Future<SmtpRcptValidator.ValidationResult> future : futures) {
            if (future.isDone() && !future.isCancelled()) {
                try {
                    SmtpRcptValidator.ValidationResult res = future.get();
                    logger.debug("Returning failed validation result with status {} on port {}", res.getStatus(), res.getPortUsed());
                    return res;
                } catch (Exception e) {
                    logger.warn("Exception while retrieving failed validation result: {}", e.getMessage());
                }
            }
        }

        logger.warn("All ports failed to validate");
        return new SmtpRcptValidator.ValidationResult(
                SmtpRcptValidator.SmtpRecipientStatus.UnknownFailure,
                -1, "All ports failed",
                "No successful validation", null, "",
                java.time.LocalDateTime.now().toString(),
                "AllPortsFailed", false, -1, false);
    }

    private String arrayToString(int[] array) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < array.length; i++) {
            if (i > 0) sb.append(", ");
            sb.append(array[i]);
        }
        sb.append("]");
        return sb.toString();
    }
}
