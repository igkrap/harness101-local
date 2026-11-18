package com.example.localinventory.framework.audit;

import jakarta.persistence.Column;
import jakarta.persistence.EntityListeners;
import jakarta.persistence.MappedSuperclass;
import java.time.LocalDateTime;
import org.springframework.data.annotation.CreatedBy;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.annotation.LastModifiedBy;
import org.springframework.data.annotation.LastModifiedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

/**
 * Who registered and who last changed a record, and when. Business entities extend this and their table has
 * created_by VARCHAR(100), created_at TIMESTAMP, updated_by VARCHAR(100), updated_at TIMESTAMP (all nullable).
 * The values are filled in automatically on save; controllers never set them.
 */
@MappedSuperclass
@EntityListeners(AuditingEntityListener.class)
public abstract class AuditedEntity {
    @CreatedBy @Column(name = "created_by", updatable = false) private String createdBy;
    @CreatedDate @Column(name = "created_at", updatable = false) private LocalDateTime createdAt;
    @LastModifiedBy @Column(name = "updated_by") private String updatedBy;
    @LastModifiedDate @Column(name = "updated_at") private LocalDateTime updatedAt;

    public String getCreatedBy() { return createdBy; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public String getUpdatedBy() { return updatedBy; }
    public LocalDateTime getUpdatedAt() { return updatedAt; }
}
