package com.fullstack.crud.entity;

import javax.persistence.Column;
import javax.persistence.Entity;
import javax.persistence.GeneratedValue;
import javax.persistence.Id;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@AllArgsConstructor
@NoArgsConstructor
@Entity
public class Task {
    @Id
    @GeneratedValue
    private int id;
    private String label;
    private String category;
    @Column(name = "subCategory")
    private String subCategory;
    private String priority;
    private String status;
    private String statusCss;
    private boolean checked;
    private String dueDate;
    private String type;
}
