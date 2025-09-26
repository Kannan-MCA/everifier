package com.k3n.everifier.repository.cache;

import com.k3n.everifier.model.cache.EmailVerificationResultEntity;
import org.springframework.data.jpa.repository.JpaRepository;

public interface emailverificationresultrepository extends JpaRepository<EmailVerificationResultEntity, Long> {
}
