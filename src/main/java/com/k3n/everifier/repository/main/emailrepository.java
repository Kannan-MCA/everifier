package com.k3n.everifier.repository.main;

import com.k3n.everifier.model.main.EmailEntity;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface emailrepository extends JpaRepository<EmailEntity, Long> {

    // Find emails that have not been processed yet
    List<EmailEntity> findByProcessedFalse();

    // Check if an email already exists in the primary database
    boolean existsByEmail(String email);
}
